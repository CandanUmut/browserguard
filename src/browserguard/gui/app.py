"""Main window, application state, and startup."""

from __future__ import annotations

import ctypes
import sys
from dataclasses import replace
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from browserguard.core import cooldown, engine
from browserguard.core.config import AppConfig, ProtectionSettings, load_config, save_config
from browserguard.core.passcode import verify_passcode
from browserguard.core.registry import is_admin
from browserguard.gui.pages import (
    DashboardPage,
    SchedulesPage,
    SecurityPage,
    VerifyPage,
    WebsitesPage,
)
from browserguard.gui.theme import COLORS, STYLESHEET
from browserguard.gui.widgets import Banner
from browserguard.version import APP_NAME, __version__


def relaunch_as_admin() -> bool:
    """Restart the app elevated. Returns True if the relaunch was started."""
    if sys.platform != "win32":
        return False
    try:
        if getattr(sys, "frozen", False):
            executable, params = sys.executable, ""
        else:
            executable = sys.executable
            params = f'-m browserguard "{" ".join(sys.argv[1:])}"'.strip()
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, params or None, None, 1
        )
        return int(result) > 32
    except Exception:  # noqa: BLE001
        return False


class Controller(QObject):
    """Holds the saved config and the draft the user is editing."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        try:
            self.config = load_config()
        except Exception:  # noqa: BLE001 - a broken file must not stop the app
            self.config = AppConfig()
        # Apply anything whose wait has already elapsed.
        self.config, promoted = cooldown.promote_due_change(self.config)
        self.promoted_on_start = promoted
        self.draft: ProtectionSettings = ProtectionSettings.from_dict(
            self.config.protection.to_dict()
        )
        self.browser_count = 0

    # -- draft ----------------------------------------------------------
    def set_draft(self, draft: ProtectionSettings) -> None:
        self.draft = draft
        self.changed.emit()

    def revert_draft(self) -> None:
        self.draft = ProtectionSettings.from_dict(self.config.protection.to_dict())
        self.changed.emit()

    def is_dirty(self) -> bool:
        return self.draft.to_dict() != self.config.protection.to_dict()

    def draft_is_loosening(self) -> bool:
        return cooldown.is_loosening(self.config.protection, self.draft)

    # -- persistence ----------------------------------------------------
    def _save_and_apply(self) -> engine.ApplyReport:
        self.config.last_applied = datetime.now(timezone.utc).isoformat()
        save_config(self.config)
        report = engine.apply_protection(self.config, deep_scan=False)
        self.changed.emit()
        return report

    def apply_draft(self, passcode: str | None = None) -> tuple[bool, str, engine.ApplyReport | None]:
        ok = self.check_passcode(passcode) if passcode else False
        self.config, result = cooldown.request_change(self.config, self.draft, passcode_ok=ok)
        if result.applied:
            report = self._save_and_apply()
            self.draft = ProtectionSettings.from_dict(self.config.protection.to_dict())
            return True, result.message, report
        save_config(self.config)
        # The draft stays visible so the user can see what is queued.
        self.changed.emit()
        return False, result.message, None

    def cancel_pending(self) -> str:
        self.config, result = cooldown.cancel_pending(self.config)
        save_config(self.config)
        self.revert_draft()
        return result.message

    def apply_pending_now(self, passcode: str) -> tuple[bool, str]:
        if not self.check_passcode(passcode):
            return False, "That passcode was not correct."
        pending = cooldown.get_pending(self.config)
        if pending is None:
            return False, "There is no pending change."
        self.config.protection = ProtectionSettings.from_dict(pending.settings)
        self.config.pending = None
        self._save_and_apply()
        self.draft = ProtectionSettings.from_dict(self.config.protection.to_dict())
        return True, "Applied."

    def check_passcode(self, passcode: str | None) -> bool:
        security = self.config.security
        if not passcode or not security.has_passcode:
            return False
        return verify_passcode(passcode, security.passcode_hash, security.passcode_salt)

    def set_cooldown(self, hours: float) -> None:
        self.config.security.cooldown_hours = hours
        save_config(self.config)
        self.changed.emit()

    def set_passcode(self, digest: str, salt: str) -> None:
        self.config.security.passcode_hash = digest
        self.config.security.passcode_salt = salt
        self.config.security.passcode_created_at = datetime.now(timezone.utc).isoformat()
        save_config(self.config)
        self.changed.emit()

    def set_schedules(self, schedules: list[dict]) -> None:
        self.config.schedules = schedules
        save_config(self.config)
        engine.apply_protection(self.config, deep_scan=False)
        self.changed.emit()

    def request_uninstall(self, parent: QWidget) -> None:
        """Removing protection is a loosening change, so it follows the same rules."""
        proposed = ProtectionSettings.from_dict(self.config.protection.to_dict())
        proposed.enabled = False
        proposed.level = "off"
        self.draft = proposed

        passcode = None
        if self.config.security.has_passcode and self.config.security.cooldown_hours > 0:
            text, ok = QInputDialog.getText(
                parent,
                "Passcode",
                "Enter the passcode to remove protection now.\n\n"
                "Leave this blank to schedule it instead - it will apply on its "
                "own once the waiting period has passed.",
            )
            passcode = text if ok else None

        applied, message, _ = self.apply_draft(passcode)
        if applied:
            engine.uninstall(deep_scan=False)
            QMessageBox.information(
                parent,
                "Protection removed",
                "All policy has been removed.\n\nRestart any open browser for the "
                "change to take effect.",
            )
        else:
            QMessageBox.information(parent, "Scheduled", message)


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1080, 760)
        self.setMinimumSize(900, 620)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFixedWidth(200)
        outer.addWidget(self.nav)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        outer.addWidget(right, 1)

        banner_holder = QWidget()
        banner_layout = QVBoxLayout(banner_holder)
        banner_layout.setContentsMargins(28, 18, 28, 0)
        banner_layout.setSpacing(8)
        self.admin_banner = Banner()
        self.pending_banner = Banner()
        banner_layout.addWidget(self.admin_banner)
        banner_layout.addWidget(self.pending_banner)
        right_layout.addWidget(banner_holder)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        self.pages = [
            ("Protection", DashboardPage(controller)),
            ("Websites", WebsitesPage(controller)),
            ("Schedules", SchedulesPage(controller)),
            ("Security", SecurityPage(controller)),
            ("Verify", VerifyPage(controller)),
        ]
        for name, page in self.pages:
            self.nav.addItem(QListWidgetItem(name))
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._page_changed)
        self.nav.setCurrentRow(0)

        self.apply_bar = QWidget()
        apply_layout = QHBoxLayout(self.apply_bar)
        apply_layout.setContentsMargins(28, 12, 28, 16)
        self.apply_note = Banner()
        self.discard_button = QPushButton("Discard changes")
        self.discard_button.clicked.connect(controller.revert_draft)
        self.apply_button = QPushButton("Apply changes")
        self.apply_button.setObjectName("Primary")
        self.apply_button.clicked.connect(self._apply)
        apply_layout.addStretch(1)
        apply_layout.addWidget(self.discard_button)
        apply_layout.addWidget(self.apply_button)
        right_layout.addWidget(self.apply_bar)
        self.apply_bar.hide()

        controller.changed.connect(self._refresh)

        # Keep the pending countdown live without hammering the disk.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_banners)
        self.timer.start(30_000)

        self._refresh()
        if controller.promoted_on_start:
            QMessageBox.information(
                self,
                "Change applied",
                "A change that was waiting reached its time and has been applied.",
            )

    def _page_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.pages[index][1].refresh()

    def closeEvent(self, event) -> None:
        """Let background work finish so the process exits cleanly."""
        self.timer.stop()
        for _, page in self.pages:
            shutdown = getattr(page, "shutdown", None)
            if shutdown is not None:
                shutdown()
        super().closeEvent(event)

    def _apply(self) -> None:
        passcode = None
        if self.controller.draft_is_loosening() and self.controller.config.security.cooldown_hours > 0:
            if self.controller.config.security.has_passcode:
                text, ok = QInputDialog.getText(
                    self,
                    "Passcode",
                    "This change reduces protection, so it waits "
                    f"{self.controller.config.security.cooldown_hours:g} hours.\n\n"
                    "Enter the passcode to apply it now, or leave blank to schedule it.",
                )
                passcode = text if ok else None
                if not ok:
                    return
        applied, message, report = self.controller.apply_draft(passcode)
        if applied:
            detail = message
            if report:
                detail += "\n\n" + report.summary()
                for warning in report.warnings:
                    detail += f"\n\nNote: {warning}"
                detail += "\n\nRestart any open browser for changes to take effect."
            QMessageBox.information(self, "Applied", detail)
        else:
            QMessageBox.information(self, "Scheduled", message)
        self._refresh()

    def _refresh(self) -> None:
        self.pages[self.nav.currentRow()][1].refresh()
        self._refresh_banners()
        dirty = self.controller.is_dirty()
        self.apply_bar.setVisible(dirty)
        if dirty:
            loosening = self.controller.draft_is_loosening()
            hours = self.controller.config.security.cooldown_hours
            if loosening and hours > 0:
                self.apply_button.setText(f"Request change (waits {hours:g}h)")
            else:
                self.apply_button.setText("Apply changes")

    def _refresh_banners(self) -> None:
        if not is_admin():
            self.admin_banner.clear_buttons()
            self.admin_banner.show_message(
                "Running without administrator rights. You can look around, but "
                "policy cannot be written until you restart elevated.",
                "warn",
            )
            self.admin_banner.add_button("Restart as administrator", self._elevate, primary=True)
        else:
            self.admin_banner.hide()

        pending = cooldown.get_pending(self.controller.config)
        self.pending_banner.clear_buttons()
        if pending:
            self.pending_banner.show_message(
                f"Waiting: {pending.summary}. Applies in "
                f"{cooldown.format_remaining(pending)} "
                f"(at {pending.apply_time.astimezone():%a %d %b, %H:%M}).",
                "info",
            )
            if self.controller.config.security.has_passcode:
                self.pending_banner.add_button("Apply now with passcode", self._apply_pending)
            self.pending_banner.add_button("Cancel it", self._cancel_pending)
        else:
            self.pending_banner.hide()

    def _apply_pending(self) -> None:
        text, ok = QInputDialog.getText(self, "Passcode", "Enter the passcode:")
        if not ok:
            return
        success, message = self.controller.apply_pending_now(text)
        QMessageBox.information(self, "Passcode", message)
        self._refresh()

    def _cancel_pending(self) -> None:
        message = self.controller.cancel_pending()
        QMessageBox.information(self, "Cancelled", message)
        self._refresh()

    def _elevate(self) -> None:
        if relaunch_as_admin():
            QApplication.quit()
        else:
            QMessageBox.warning(
                self,
                "Could not restart",
                "The elevation prompt was declined or failed. Right-click "
                f"{APP_NAME} and choose 'Run as administrator' instead.",
            )


def _icon() -> QIcon:
    """A simple generated icon so the window and taskbar are not blank."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    from PySide6.QtGui import QBrush, QColor, QPainter

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QBrush(QColor(COLORS["accent"])))
    painter.setPen(Qt.NoPen)
    points = [(32, 4), (58, 16), (58, 36), (32, 60), (6, 36), (6, 16)]
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF

    painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setPixelSize(30)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "B")
    painter.end()
    return QIcon(pixmap)


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(_icon())

    controller = Controller()
    window = MainWindow(controller)
    window.show()
    return app.exec()
