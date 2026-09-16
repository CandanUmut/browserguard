"""First-run setup.

Walks through the whole thing in a few steps, applies it, and finishes by
showing how to undo it. Nothing here is mandatory - every choice has a sensible
default already selected, so the whole wizard can be completed by pressing
Continue repeatedly.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from browserguard.core import blocklists, engine
from browserguard.core.config import (
    COOLDOWN_CHOICES,
    LEVEL_LIGHT,
    LEVEL_MODERATE,
    LEVEL_STRICT,
    format_cooldown,
    preset,
)
from browserguard.core.passcode import generate_passcode, hash_passcode
from browserguard.core.registry import is_admin
from browserguard.gui.pages import PasscodeDialog
from browserguard.gui.theme import COLORS
from browserguard.gui.widgets import ChoiceCard, dim

STEP_WELCOME = "welcome"
STEP_LEVEL = "level"
STEP_WAIT = "wait"
STEP_PASSCODE = "passcode"
STEP_APPLY = "apply"
STEP_DONE = "done"


class _Step(QWidget):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(13)

        heading = QLabel(title)
        heading.setObjectName("WizardTitle")
        heading.setWordWrap(True)
        self.column.addWidget(heading)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Subtitle")
            sub.setWordWrap(True)
            self.column.addWidget(sub)

    def on_enter(self) -> None:
        """Called each time the step is shown."""


class SetupWizard(QDialog):
    """The guided first-run flow."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Set up BrowserGuard")
        self.setMinimumSize(760, 560)

        self.level = LEVEL_MODERATE
        self.cooldown_hours = 0.0
        self.passcode_created = False
        self.report: engine.ApplyReport | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 28, 34, 22)
        outer.setSpacing(16)

        self.step_label = QLabel("")
        self.step_label.setObjectName("WizardStep")
        outer.addWidget(self.step_label)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        self.steps: list[str] = [STEP_WELCOME, STEP_LEVEL, STEP_WAIT, STEP_PASSCODE, STEP_APPLY, STEP_DONE]
        self.widgets: dict[str, _Step] = {
            STEP_WELCOME: self._build_welcome(),
            STEP_LEVEL: self._build_level(),
            STEP_WAIT: self._build_wait(),
            STEP_PASSCODE: self._build_passcode(),
            STEP_APPLY: self._build_apply(),
            STEP_DONE: self._build_done(),
        }
        for key in self.steps:
            self.stack.addWidget(self.widgets[key])

        controls = QHBoxLayout()
        controls.setSpacing(9)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._back)
        controls.addWidget(self.back_button)
        controls.addStretch(1)
        self.skip_button = QPushButton("Skip setup")
        self.skip_button.clicked.connect(self.reject)
        controls.addWidget(self.skip_button)
        self.next_button = QPushButton("Continue")
        self.next_button.setObjectName("Primary")
        self.next_button.setMinimumWidth(150)
        self.next_button.setMinimumHeight(40)
        self.next_button.clicked.connect(self._next)
        controls.addWidget(self.next_button)
        outer.addLayout(controls)

        self._index = 0
        self._show_step()

    # -- steps ----------------------------------------------------------
    def _build_welcome(self) -> _Step:
        step = _Step(
            "Let's set up BrowserGuard",
            "This takes about a minute. Everything you pick can be changed afterwards.",
        )
        for title, body in (
            (
                "It covers every browser at once",
                "Chrome, Edge, Brave, Firefox, Opera, Vivaldi and unbranded "
                "Chromium browsers such as Ecosia - including ones installed later.",
            ),
            (
                "The browser does the blocking",
                "So it keeps working in private windows, and cannot be switched "
                "off from the browser's own settings.",
            ),
            (
                "Nothing is ever locked",
                "You can undo all of it at any time. The last step shows you how, "
                "before you finish.",
            ),
        ):
            card = ChoiceCard(title, body)
            card.setCursor(Qt.ArrowCursor)
            step.column.addWidget(card)

        self.admin_note = dim("")
        step.column.addWidget(self.admin_note)
        step.column.addStretch(1)
        return step

    def _build_level(self) -> _Step:
        step = _Step(
            "How strict should it be?",
            "Moderate suits most families. You can fine-tune every detail later.",
        )
        self.level_cards: dict[str, ChoiceCard] = {}
        for level_id, title, body in (
            (
                LEVEL_LIGHT,
                "Light",
                "Adult sites and proxy/VPN sites blocked, SafeSearch forced. "
                "Nothing else is restricted.",
            ),
            (
                LEVEL_MODERATE,
                "Moderate  ·  suggested",
                "Light, plus gambling and dating, no private browsing, and no "
                "developer tools.",
            ),
            (
                LEVEL_STRICT,
                "Strict",
                "Moderate, plus social media and gaming, guest profiles off and "
                "new extensions blocked.",
            ),
        ):
            card = ChoiceCard(title, body)
            card.clicked.connect(lambda l=level_id: self._pick_level(l))
            self.level_cards[level_id] = card
            step.column.addWidget(card)
        step.column.addStretch(1)
        return step

    def _build_wait(self) -> _Step:
        step = _Step(
            "Should reducing protection have to wait?",
            "A waiting period means protection can still be reduced - it just "
            "cannot be done on impulse. This is entirely optional.",
        )
        self.wait_cards: dict[float, ChoiceCard] = {}
        for hours, _ in COOLDOWN_CHOICES:
            if hours <= 0:
                title, body = "No waiting period", "Every change applies straight away."
            elif hours == 0.25:
                title = "15 minutes  ·  suggested"
                body = "Long enough to think twice, short enough to never feel trapped."
            else:
                title = format_cooldown(hours)
                body = f"Reducing protection waits {format_cooldown(hours)} before it applies."
            card = ChoiceCard(title, body)
            card.clicked.connect(lambda h=hours: self._pick_wait(h))
            self.wait_cards[hours] = card
            step.column.addWidget(card)
        step.column.addWidget(
            dim(
                "Making protection stronger is always immediate. Only reductions wait."
            )
        )
        step.column.addStretch(1)
        return step

    def _build_passcode(self) -> _Step:
        step = _Step(
            "Want a passcode to skip the wait?",
            "The passcode does one thing: it applies a reduction immediately "
            "instead of waiting. It is never needed to open this app.",
        )
        self.passcode_status = QLabel("")
        self.passcode_status.setWordWrap(True)
        step.column.addWidget(self.passcode_status)

        button_row = QHBoxLayout()
        button_row.setSpacing(9)
        self.create_passcode_button = QPushButton("Create a passcode")
        self.create_passcode_button.setObjectName("Primary")
        self.create_passcode_button.setMinimumHeight(40)
        self.create_passcode_button.clicked.connect(self._create_passcode)
        button_row.addWidget(self.create_passcode_button)
        button_row.addStretch(1)
        step.column.addLayout(button_row)

        step.column.addWidget(
            dim(
                "If you skip this, or lose the passcode later, nothing is lost - a "
                "change still applies once the waiting period has passed on its own."
            )
        )
        step.column.addStretch(1)
        return step

    def _build_apply(self) -> _Step:
        step = _Step("Ready to apply", "")
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']};"
            " border-radius: 10px; padding: 16px; font-size: 14px;"
        )
        step.column.addWidget(self.summary_label)
        self.apply_result = QLabel("")
        self.apply_result.setWordWrap(True)
        step.column.addWidget(self.apply_result)
        step.column.addStretch(1)
        return step

    def _build_done(self) -> _Step:
        step = _Step(
            "You're protected",
            "One last thing worth knowing before you go.",
        )
        self.done_summary = QLabel("")
        self.done_summary.setWordWrap(True)
        self.done_summary.setStyleSheet(
            f"background: {COLORS['good_soft']}; border: 1px solid {COLORS['good']};"
            " border-radius: 10px; padding: 16px;"
        )
        step.column.addWidget(self.done_summary)

        undo = ChoiceCard(
            "How to undo any of this",
            "Open BrowserGuard, go to Security, and choose 'Turn off all "
            "protection'. That removes every setting it wrote and the background "
            "task with it. Individual settings can be changed on the Protection "
            "and Websites pages at any time.",
        )
        undo.setCursor(Qt.ArrowCursor)
        step.column.addWidget(undo)

        self.undo_detail = ChoiceCard("", "")
        self.undo_detail.setCursor(Qt.ArrowCursor)
        step.column.addWidget(self.undo_detail)

        step.column.addWidget(
            dim(
                "Restart any browser that is already open, so it picks up the new "
                "settings."
            )
        )
        step.column.addStretch(1)
        return step

    # -- interactions ---------------------------------------------------
    def _pick_level(self, level: str) -> None:
        self.level = level
        for level_id, card in self.level_cards.items():
            card.set_selected(level_id == level)

    def _pick_wait(self, hours: float) -> None:
        self.cooldown_hours = hours
        for value, card in self.wait_cards.items():
            card.set_selected(abs(value - hours) < 1e-6)

    def _create_passcode(self) -> None:
        code = generate_passcode()
        digest, salt = hash_passcode(code)
        self.controller.set_passcode(digest, salt)
        PasscodeDialog(code, self).exec()
        self.passcode_created = True
        self._refresh_passcode_step()

    def _refresh_passcode_step(self) -> None:
        if self.passcode_created:
            self.passcode_status.setText("A passcode has been created.")
            self.create_passcode_button.setText("Create a different one")
        else:
            self.passcode_status.setText("No passcode yet - that is a fine choice too.")
            self.create_passcode_button.setText("Create a passcode")

    def _current_key(self) -> str:
        return self.steps[self._index]

    def _show_step(self) -> None:
        key = self._current_key()
        self.stack.setCurrentWidget(self.widgets[key])
        self.widgets[key].on_enter()

        visible = [k for k in self.steps if not self._is_skipped(k)]
        position = visible.index(key) + 1 if key in visible else 1
        self.step_label.setText(f"Step {position} of {len(visible)}")

        self.back_button.setVisible(self._index > 0 and key != STEP_DONE)
        self.skip_button.setVisible(key not in (STEP_APPLY, STEP_DONE))

        if key == STEP_WELCOME:
            self.admin_note.setText(
                ""
                if is_admin()
                else "Note: BrowserGuard is not running as administrator, so it will "
                "not be able to apply anything. Close it and choose 'Run as "
                "administrator'."
            )
            self.next_button.setText("Get started")
        elif key == STEP_LEVEL:
            self._pick_level(self.level)
            self.next_button.setText("Continue")
        elif key == STEP_WAIT:
            self._pick_wait(self.cooldown_hours)
            self.next_button.setText("Continue")
        elif key == STEP_PASSCODE:
            self._refresh_passcode_step()
            self.next_button.setText("Continue")
        elif key == STEP_APPLY:
            self._prepare_summary()
            self.next_button.setText("Apply now")
        elif key == STEP_DONE:
            self.next_button.setText("Finish")

    def _is_skipped(self, key: str) -> bool:
        # A passcode only has meaning when there is a wait for it to skip.
        return key == STEP_PASSCODE and self.cooldown_hours <= 0

    def _prepare_summary(self) -> None:
        settings = preset(self.level)
        categories = ", ".join(settings.blocked_categories)
        count = len(blocklists.expand_categories(settings.blocked_categories))
        lines = [
            f"<b>Protection level:</b> {self.level}",
            f"<b>Blocking:</b> {categories} ({count} sites)",
            f"<b>Waiting period:</b> {format_cooldown(self.cooldown_hours)}",
            f"<b>Passcode:</b> {'created' if self.passcode_created else 'none'}",
            "<b>Applies to:</b> every browser on this computer, including ones installed later",
        ]
        self.summary_label.setText("<br>".join(lines))
        self.apply_result.setText("")

    def _apply(self) -> bool:
        settings = preset(self.level)
        settings.custom_blocked = self.controller.config.protection.custom_blocked
        settings.allowed = self.controller.config.protection.allowed

        self.controller.config.protection = settings
        self.controller.config.security.cooldown_hours = self.cooldown_hours
        self.controller.config.setup_complete = True
        self.controller.draft = settings

        try:
            report = self.controller.apply_setup()
        except Exception as exc:  # noqa: BLE001
            self.apply_result.setText(f"Could not apply: {exc}")
            return False
        self.report = report
        if not report.ok:
            failed = [r for r in report.results if r.error][:2]
            detail = "; ".join(f"{r.name}: {r.error}" for r in failed)
            self.apply_result.setText(f"Applied with problems - {detail}")
        return True

    def _next(self) -> None:
        key = self._current_key()

        if key == STEP_APPLY:
            if not self._apply():
                return
            installed = sum(1 for r in (self.report.results if self.report else []) if r.installed)
            covered = self.report.browsers_covered if self.report else 0
            self.done_summary.setText(
                f"Protection is on. Policy was written for {covered} browser "
                f"targets, {installed} of which are installed right now."
            )
            if self.cooldown_hours > 0:
                self.undo_detail.title_label.setText(
                    f"Reducing protection waits {format_cooldown(self.cooldown_hours)}"
                )
                self.undo_detail.description_label.setText(
                    "Making it stronger is always instant. A reduction is scheduled "
                    "and applies on its own once the wait is over"
                    + (
                        " - or immediately if you enter the passcode."
                        if self.passcode_created
                        else ". There is no passcode, so waiting is the way."
                    )
                )
            else:
                self.undo_detail.title_label.setText("Changes apply straight away")
                self.undo_detail.description_label.setText(
                    "You chose no waiting period, so anything you change - including "
                    "turning protection off - takes effect immediately."
                )
            self.undo_detail.setVisible(True)

        if key == STEP_DONE:
            self.accept()
            return

        self._index += 1
        while self._index < len(self.steps) - 1 and self._is_skipped(self._current_key()):
            self._index += 1
        self._show_step()

    def _back(self) -> None:
        self._index -= 1
        while self._index > 0 and self._is_skipped(self._current_key()):
            self._index -= 1
        self._index = max(0, self._index)
        self._show_step()
