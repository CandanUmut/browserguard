"""The five pages of the interface."""

from __future__ import annotations

import socket
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTime, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTimeEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from browserguard.core import blocklists, cooldown, engine, scheduler
from browserguard.core.config import (
    LEVEL_DESCRIPTIONS,
    LEVEL_LIGHT,
    LEVEL_MODERATE,
    LEVEL_OFF,
    LEVEL_STRICT,
    preset,
)
from browserguard.core.passcode import export_passcode, generate_passcode, hash_passcode
from browserguard.core.schedules import DAY_NAMES, Schedule, load_schedules, next_transition
from browserguard.gui.theme import COLORS
from browserguard.gui.widgets import Card, PageHeader, colored, dim, row


class Page(QWidget):
    """Base page: a scrollable column of cards."""

    def __init__(self, controller, title: str, subtitle: str):
        super().__init__()
        self.controller = controller

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)
        self.column = QVBoxLayout(inner)
        self.column.setContentsMargins(28, 24, 28, 24)
        self.column.setSpacing(16)
        self.column.addWidget(PageHeader(title, subtitle))

    def finish(self) -> None:
        self.column.addStretch(1)

    def refresh(self) -> None:
        """Called when the page becomes visible."""


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class DashboardPage(Page):
    LEVELS = (
        (LEVEL_OFF, "Off"),
        (LEVEL_LIGHT, "Light"),
        (LEVEL_MODERATE, "Moderate"),
        (LEVEL_STRICT, "Strict"),
    )

    def __init__(self, controller):
        super().__init__(
            controller,
            "Protection",
            "Choose how much to restrict. Stronger settings apply immediately; "
            "weaker ones go through the waiting period.",
        )

        status_card = Card()
        self.status_label = QLabel("...")
        self.status_label.setObjectName("StatusBig")
        status_card.add(self.status_label)
        self.status_detail = dim("")
        status_card.add(self.status_detail)
        self.column.addWidget(status_card)

        level_card = Card("Protection level", "")
        self.level_buttons: dict[str, QPushButton] = {}
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        for level_id, label in self.LEVELS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.clicked.connect(lambda _=False, l=level_id: self._pick_level(l))
            self.level_buttons[level_id] = button
            button_row.addWidget(button, 1)
        level_card.add_layout(button_row)
        self.level_description = dim("")
        level_card.add(self.level_description)
        self.column.addWidget(level_card)

        options_card = Card(
            "Options",
            "These apply on top of the level you picked. Changing one switches "
            "the level to Custom.",
        )
        self.toggles: dict[str, QCheckBox] = {}
        for attr, label, hint in (
            ("safe_search", "Force SafeSearch", "Google and Bing return filtered results only."),
            (
                "safe_sites",
                "Google SafeSites adult filter",
                "Chrome classifies pages as it loads them, so it catches adult "
                "sites that are not on any blocklist.",
            ),
            (
                "block_incognito",
                "Block private browsing",
                "Private windows would otherwise sidestep nothing here, but they "
                "do hide history.",
            ),
            (
                "block_devtools",
                "Block developer tools",
                "Without this, F12 can be used to edit the page and inspect requests.",
            ),
            ("block_guest_mode", "Block guest profiles", "A guest profile starts with no policy applied."),
            (
                "force_plain_dns",
                "Block the browser's encrypted DNS",
                "Browser-level DoH bypasses any DNS filtering set up on this machine.",
            ),
            (
                "lock_extensions",
                "Block new extensions",
                "Stops new installs. Extensions already installed keep working.",
            ),
        ):
            box = QCheckBox(label)
            box.setToolTip(hint)
            box.toggled.connect(lambda checked, a=attr: self._toggle(a, checked))
            self.toggles[attr] = box
            options_card.add(box)
            options_card.add(dim("     " + hint))

        youtube_row = QHBoxLayout()
        youtube_row.addWidget(QLabel("YouTube Restricted Mode"))
        self.youtube = QComboBox()
        self.youtube.addItems(["off", "moderate", "strict"])
        self.youtube.currentTextChanged.connect(self._set_youtube)
        youtube_row.addWidget(self.youtube)
        youtube_row.addStretch(1)
        options_card.add_layout(youtube_row)
        options_card.add(
            dim(
                "     Restricted Mode hides every YouTube comment and blocks most "
                "live streams. That surprises people, so it is off by default."
            )
        )
        self.column.addWidget(options_card)
        self.finish()

    def _pick_level(self, level: str) -> None:
        kept_custom = self.controller.draft.custom_blocked
        kept_allowed = self.controller.draft.allowed
        draft = preset(level)
        draft.custom_blocked = kept_custom
        draft.allowed = kept_allowed
        self.controller.set_draft(draft)

    def _toggle(self, attribute: str, checked: bool) -> None:
        if getattr(self.controller.draft, attribute) == checked:
            return
        draft = replace(self.controller.draft, **{attribute: checked})
        draft.level = "custom"
        self.controller.set_draft(draft)

    def _set_youtube(self, mode: str) -> None:
        if self.controller.draft.youtube_restrict == mode:
            return
        draft = replace(self.controller.draft, youtube_restrict=mode)
        draft.level = "custom"
        self.controller.set_draft(draft)

    def refresh(self) -> None:
        draft = self.controller.draft
        live = self.controller.config.protection

        if live.enabled:
            self.status_label.setText("Protected")
            self.status_label.setStyleSheet(f"color: {COLORS['good']};")
        else:
            self.status_label.setText("Not protected")
            self.status_label.setStyleSheet(f"color: {COLORS['bad']};")

        blocked = len(
            blocklists.expand_categories(live.blocked_categories)
        ) + len(live.custom_blocked)
        schedules = load_schedules(self.controller.config.schedules)
        self.status_detail.setText(
            f"Level in force: {live.level}  -  {blocked} sites blocked  -  "
            f"{self.controller.browser_count} browser policy keys  -  "
            f"{next_transition(schedules)}"
        )

        for level_id, button in self.level_buttons.items():
            button.setChecked(draft.level == level_id)
            button.setObjectName("Primary" if draft.level == level_id else "")
            button.style().unpolish(button)
            button.style().polish(button)
        self.level_description.setText(LEVEL_DESCRIPTIONS.get(draft.level, ""))

        for attribute, box in self.toggles.items():
            box.blockSignals(True)
            box.setChecked(getattr(draft, attribute))
            box.blockSignals(False)
        self.youtube.blockSignals(True)
        self.youtube.setCurrentText(draft.youtube_restrict)
        self.youtube.blockSignals(False)


# ---------------------------------------------------------------------------
# Websites
# ---------------------------------------------------------------------------


class WebsitesPage(Page):
    def __init__(self, controller):
        super().__init__(
            controller,
            "Websites",
            "Pick categories to block, and add your own sites on top.",
        )

        category_card = Card(
            "Categories",
            "Bundled lists, stored inside the app so they work with no internet "
            "connection. A list can only cover sites someone has listed, which is "
            "why the SafeSites filter and DNS filtering matter alongside it.",
        )
        self.category_boxes: dict[str, QCheckBox] = {}
        for category in blocklists.CATEGORIES:
            box = QCheckBox(f"{category.name}  ({blocklists.category_size(category.id)} sites)")
            box.setToolTip(category.description)
            box.toggled.connect(lambda checked, c=category.id: self._toggle_category(c, checked))
            self.category_boxes[category.id] = box
            category_card.add(box)
            category_card.add(dim("     " + category.description))
        self.column.addWidget(category_card)

        blocked_card = Card("Blocked sites", "Your own entries, on top of the categories above.")
        self.blocked_list = QListWidget()
        self.blocked_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.blocked_list.setMinimumHeight(130)
        blocked_card.add(self.blocked_list)
        self.blocked_input = QLineEdit()
        self.blocked_input.setPlaceholderText("example.com")
        self.blocked_input.returnPressed.connect(self._add_blocked)
        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_blocked)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_blocked)
        blocked_card.add_layout(row(self.blocked_input, add_button, remove_button))
        self.column.addWidget(blocked_card)

        allowed_card = Card(
            "Always allowed",
            "Exceptions that beat the blocklist. Adding one reduces protection, so "
            "it goes through the waiting period.",
        )
        self.allowed_list = QListWidget()
        self.allowed_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.allowed_list.setMinimumHeight(110)
        allowed_card.add(self.allowed_list)
        self.allowed_input = QLineEdit()
        self.allowed_input.setPlaceholderText("school.example.edu")
        self.allowed_input.returnPressed.connect(self._add_allowed)
        allow_add = QPushButton("Add")
        allow_add.clicked.connect(self._add_allowed)
        allow_remove = QPushButton("Remove selected")
        allow_remove.clicked.connect(self._remove_allowed)
        allowed_card.add_layout(row(self.allowed_input, allow_add, allow_remove))

        self.allowlist_only = QCheckBox("Allowlist only - block every site except those listed above")
        self.allowlist_only.toggled.connect(self._toggle_allowlist_only)
        allowed_card.add(self.allowlist_only)
        allowed_card.add(
            dim(
                "     The strictest possible setting. With an empty allowlist the "
                "browser cannot reach anything at all."
            )
        )
        self.column.addWidget(allowed_card)
        self.finish()

    def _toggle_category(self, category_id: str, checked: bool) -> None:
        categories = list(self.controller.draft.blocked_categories)
        if checked and category_id not in categories:
            categories.append(category_id)
        elif not checked and category_id in categories:
            categories.remove(category_id)
        else:
            return
        draft = replace(self.controller.draft, blocked_categories=categories)
        draft.level = "custom"
        self.controller.set_draft(draft)

    def _add_to(self, attribute: str, widget: QLineEdit) -> None:
        pattern = blocklists.normalise_pattern(widget.text())
        if not pattern:
            return
        values = list(getattr(self.controller.draft, attribute))
        if pattern not in values:
            values.append(pattern)
            draft = replace(self.controller.draft, **{attribute: values})
            self.controller.set_draft(draft)
        widget.clear()

    def _remove_from(self, attribute: str, widget: QListWidget) -> None:
        selected = {item.text() for item in widget.selectedItems()}
        if not selected:
            return
        values = [v for v in getattr(self.controller.draft, attribute) if v not in selected]
        self.controller.set_draft(replace(self.controller.draft, **{attribute: values}))

    def _add_blocked(self) -> None:
        self._add_to("custom_blocked", self.blocked_input)

    def _remove_blocked(self) -> None:
        self._remove_from("custom_blocked", self.blocked_list)

    def _add_allowed(self) -> None:
        self._add_to("allowed", self.allowed_input)

    def _remove_allowed(self) -> None:
        self._remove_from("allowed", self.allowed_list)

    def _toggle_allowlist_only(self, checked: bool) -> None:
        if self.controller.draft.allowlist_only == checked:
            return
        draft = replace(self.controller.draft, allowlist_only=checked)
        draft.level = "custom"
        self.controller.set_draft(draft)

    def refresh(self) -> None:
        draft = self.controller.draft
        for category_id, box in self.category_boxes.items():
            box.blockSignals(True)
            box.setChecked(category_id in draft.blocked_categories)
            box.blockSignals(False)
        self.blocked_list.clear()
        self.blocked_list.addItems(draft.custom_blocked)
        self.allowed_list.clear()
        self.allowed_list.addItems(draft.allowed)
        self.allowlist_only.blockSignals(True)
        self.allowlist_only.setChecked(draft.allowlist_only)
        self.allowlist_only.blockSignals(False)


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


class ScheduleDialog(QDialog):
    def __init__(self, schedule: Schedule, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Schedule")
        self.setMinimumWidth(430)
        self.schedule = schedule

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.name = QLineEdit(schedule.name)
        layout.addWidget(QLabel("Name"))
        layout.addWidget(self.name)

        layout.addWidget(QLabel("Days"))
        day_row = QHBoxLayout()
        self.day_boxes: list[QCheckBox] = []
        for index, label in enumerate(DAY_NAMES):
            box = QCheckBox(label)
            box.setChecked(index in schedule.days)
            self.day_boxes.append(box)
            day_row.addWidget(box)
        layout.addLayout(day_row)

        time_row = QHBoxLayout()
        self.start = QTimeEdit(QTime.fromString(schedule.start, "HH:mm"))
        self.start.setDisplayFormat("HH:mm")
        self.end = QTimeEdit(QTime.fromString(schedule.end, "HH:mm"))
        self.end.setDisplayFormat("HH:mm")
        time_row.addWidget(QLabel("From"))
        time_row.addWidget(self.start)
        time_row.addWidget(QLabel("until"))
        time_row.addWidget(self.end)
        time_row.addStretch(1)
        layout.addLayout(time_row)
        layout.addWidget(
            dim("A window that ends earlier than it starts runs overnight, e.g. 22:00 until 06:00.")
        )

        layout.addWidget(QLabel("Block these categories during the window"))
        self.category_boxes: dict[str, QCheckBox] = {}
        for category in blocklists.CATEGORIES:
            box = QCheckBox(category.name)
            box.setChecked(category.id in schedule.categories)
            self.category_boxes[category.id] = box
            layout.addWidget(box)

        layout.addWidget(QLabel("Extra sites to block (comma separated)"))
        self.urls = QLineEdit(", ".join(schedule.urls))
        layout.addWidget(self.urls)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_schedule(self) -> Schedule:
        return Schedule(
            id=self.schedule.id,
            name=self.name.text().strip() or "Schedule",
            enabled=self.schedule.enabled,
            days=[i for i, box in enumerate(self.day_boxes) if box.isChecked()],
            start=self.start.time().toString("HH:mm"),
            end=self.end.time().toString("HH:mm"),
            categories=[cid for cid, box in self.category_boxes.items() if box.isChecked()],
            urls=[
                blocklists.normalise_pattern(u)
                for u in self.urls.text().split(",")
                if blocklists.normalise_pattern(u)
            ],
        )


class SchedulesPage(Page):
    def __init__(self, controller):
        super().__init__(
            controller,
            "Schedules",
            "Add restrictions during set hours, for example blocking social media "
            "during school time. A schedule can only add restrictions, never remove one.",
        )

        card = Card("Your schedules", "")
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(190)
        self.list_widget.itemDoubleClicked.connect(lambda _: self._edit())
        self.list_widget.itemChanged.connect(self._item_changed)
        card.add(self.list_widget)

        add_button = QPushButton("Add schedule")
        add_button.setObjectName("Primary")
        add_button.clicked.connect(self._add)
        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(self._edit)
        delete_button = QPushButton("Delete")
        delete_button.setObjectName("Danger")
        delete_button.clicked.connect(self._delete)
        card.add_layout(row(add_button, edit_button, delete_button))
        self.column.addWidget(card)

        self.note = Card(
            "Background task",
            "Schedules need a background task so policy changes when a window "
            "opens or closes. Set it up on the Security page.",
        )
        self.column.addWidget(self.note)
        self.finish()

    def _schedules(self) -> list[Schedule]:
        return load_schedules(self.controller.config.schedules)

    def _save(self, schedules: list[Schedule]) -> None:
        self.controller.set_schedules([s.to_dict() for s in schedules])

    def _add(self) -> None:
        dialog = ScheduleDialog(Schedule(), self)
        if dialog.exec() == QDialog.Accepted:
            schedules = self._schedules()
            schedules.append(dialog.result_schedule())
            self._save(schedules)

    def _selected_index(self) -> int:
        return self.list_widget.currentRow()

    def _edit(self) -> None:
        index = self._selected_index()
        schedules = self._schedules()
        if index < 0 or index >= len(schedules):
            return
        dialog = ScheduleDialog(schedules[index], self)
        if dialog.exec() == QDialog.Accepted:
            schedules[index] = dialog.result_schedule()
            self._save(schedules)

    def _delete(self) -> None:
        index = self._selected_index()
        schedules = self._schedules()
        if index < 0 or index >= len(schedules):
            return
        if (
            QMessageBox.question(self, "Delete schedule", f"Delete '{schedules[index].name}'?")
            == QMessageBox.Yes
        ):
            del schedules[index]
            self._save(schedules)

    def _item_changed(self, item) -> None:
        index = self.list_widget.row(item)
        schedules = self._schedules()
        if 0 <= index < len(schedules):
            enabled = item.checkState() == Qt.Checked
            if schedules[index].enabled != enabled:
                schedules[index].enabled = enabled
                self._save(schedules)

    def refresh(self) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for schedule in self._schedules():
            from PySide6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(f"{schedule.name}  -  {schedule.describe()}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if schedule.enabled else Qt.Unchecked)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class SecurityPage(Page):
    def __init__(self, controller):
        super().__init__(
            controller,
            "Waiting period & passcode",
            "How long a change has to wait before it takes effect, and the code "
            "that skips that wait.",
        )

        explain = Card("How this works", "")
        for line in (
            "Making protection stronger takes effect immediately.",
            "Making protection weaker waits, then applies on its own.",
            "The passcode only skips the wait.",
            "If you lose the passcode nothing is locked - the change still lands "
            "once the wait is over.",
        ):
            explain.add(dim("  -  " + line))
        self.column.addWidget(explain)

        wait_card = Card(
            "Waiting period",
            "Long enough to outlast an impulse. Lengthening it takes effect now; "
            "shortening it needs the passcode.",
        )
        self.hours = QDoubleSpinBox()
        self.hours.setRange(0, 720)
        self.hours.setDecimals(1)
        self.hours.setSingleStep(1)
        self.hours.setSuffix(" hours")
        save_wait = QPushButton("Save")
        save_wait.clicked.connect(self._save_cooldown)
        wait_card.add_layout(row(self.hours, save_wait))
        wait_card.add(dim("Set to 0 to apply every change immediately."))
        self.column.addWidget(wait_card)

        passcode_card = Card(
            "Passcode",
            "Generating a new one replaces the old. The code is shown once and "
            "written to a text file - keep it somewhere other than this computer, "
            "or give it to someone you trust.",
        )
        self.passcode_status = dim("")
        passcode_card.add(self.passcode_status)
        generate = QPushButton("Generate new passcode")
        generate.setObjectName("Primary")
        generate.clicked.connect(self._generate_passcode)
        passcode_card.add_layout(row(generate))
        self.column.addWidget(passcode_card)

        background_card = Card(
            "Background task",
            "Required for schedules, and it makes a waiting change land even if "
            "nobody opens this app. It appears in Windows Task Scheduler as "
            "'BrowserGuard Sync' and is not hidden.",
        )
        self.background_status = dim("")
        background_card.add(self.background_status)
        self.background_button = QPushButton("")
        self.background_button.clicked.connect(self._toggle_background)
        background_card.add_layout(row(self.background_button))
        self.column.addWidget(background_card)

        remove_card = Card(
            "Remove all protection",
            "Deletes every policy BrowserGuard wrote and removes the background "
            "task. Policy set by anyone else is left alone.",
        )
        remove_button = QPushButton("Remove all protection")
        remove_button.setObjectName("Danger")
        remove_button.clicked.connect(self._uninstall)
        remove_card.add_layout(row(remove_button))
        self.column.addWidget(remove_card)
        self.finish()

    def _save_cooldown(self) -> None:
        new_hours = self.hours.value()
        old_hours = self.controller.config.security.cooldown_hours
        if new_hours < old_hours:
            passcode, ok = QInputDialog.getText(
                self,
                "Passcode required",
                f"Shortening the wait from {old_hours}h to {new_hours}h reduces "
                "protection.\nEnter the passcode, or cancel and change it after "
                "the current period has passed.",
            )
            if not ok:
                return
            if not self.controller.check_passcode(passcode):
                QMessageBox.warning(self, "Passcode", "That passcode was not correct.")
                return
        self.controller.set_cooldown(new_hours)
        QMessageBox.information(self, "Saved", f"Waiting period is now {new_hours} hours.")

    def _generate_passcode(self) -> None:
        code = generate_passcode()
        default = str(Path.home() / "BrowserGuard-passcode.txt")
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save passcode file", default, "Text files (*.txt)"
        )
        if not destination:
            return
        digest, salt = hash_passcode(code)
        self.controller.set_passcode(digest, salt)
        export_passcode(code, Path(destination), machine_name=socket.gethostname())
        QMessageBox.information(
            self,
            "New passcode",
            f"Your passcode is:\n\n{code}\n\nSaved to:\n{destination}\n\n"
            "This is the only time it is shown. It is only ever needed to skip "
            "the waiting period.",
        )
        self.refresh()

    def _toggle_background(self) -> None:
        if scheduler.is_registered():
            ok, message = scheduler.unregister()
        else:
            ok, message = scheduler.register()
        QMessageBox.information(self, "Background task", message)
        self.refresh()

    def _uninstall(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Remove all protection",
                "Remove every policy BrowserGuard wrote?\n\nIf a waiting period is "
                "set, this still has to go through it unless you enter the passcode.",
            )
            != QMessageBox.Yes
        ):
            return
        self.controller.request_uninstall(self)

    def refresh(self) -> None:
        security = self.controller.config.security
        self.hours.blockSignals(True)
        self.hours.setValue(security.cooldown_hours)
        self.hours.blockSignals(False)
        self.passcode_status.setText(
            "A passcode is set." if security.has_passcode else "No passcode set yet."
        )
        registered = scheduler.is_registered()
        self.background_status.setText(
            "Running every 5 minutes." if registered else "Not set up."
        )
        self.background_button.setText("Remove background task" if registered else "Set up background task")


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


class _DetectWorker(QThread):
    finished_with = Signal(list)

    def run(self) -> None:  # pragma: no cover - thread body
        try:
            rows = engine.verify(deep_scan=True)
        except Exception:  # noqa: BLE001
            rows = []
        self.finished_with.emit(rows)


class VerifyPage(Page):
    def __init__(self, controller):
        super().__init__(
            controller,
            "Verify",
            "What is actually written to the registry right now, read back "
            "browser by browser. Cross-check it in the browser at chrome://policy.",
        )

        card = Card("Browsers and live policy", "")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Browser / policy", "Value"])
        self.tree.setColumnWidth(0, 330)
        self.tree.setMinimumHeight(420)
        card.add(self.tree)
        self.refresh_button = QPushButton("Rescan")
        self.refresh_button.setObjectName("Primary")
        self.refresh_button.clicked.connect(self.refresh)
        card.add_layout(row(self.refresh_button))
        self.column.addWidget(card)
        self.finish()
        self._worker: _DetectWorker | None = None

    def shutdown(self) -> None:
        """Let a running scan finish before the process exits.

        A QThread destroyed while still running aborts the process, which is
        what happens if the window is closed mid-scan.
        """
        worker = self._worker
        if worker is not None and worker.isRunning():
            try:
                worker.finished_with.disconnect(self._populate)
            except (RuntimeError, TypeError):
                pass
            worker.wait(5000)

    def refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Scanning...")
        self._worker = _DetectWorker()
        self._worker.finished_with.connect(self._populate)
        self._worker.start()

    def _populate(self, rows: list) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Rescan")
        self.tree.clear()
        for entry in rows:
            state = "installed" if entry["installed"] else entry["detected_via"]
            parent = QTreeWidgetItem([f"{entry['name']}  [{state}]", entry["policy_key"]])
            applied = entry["applied"]
            if not applied:
                child = QTreeWidgetItem(["no policy applied", ""])
                parent.addChild(child)
            for name, value in sorted(applied.items()):
                if isinstance(value, list):
                    text = f"{len(value)} entries"
                    node = QTreeWidgetItem([name, text])
                    for item in value[:40]:
                        node.addChild(QTreeWidgetItem(["", str(item)]))
                    if len(value) > 40:
                        node.addChild(QTreeWidgetItem(["", f"... +{len(value) - 40} more"]))
                    parent.addChild(node)
                else:
                    parent.addChild(QTreeWidgetItem([name, str(value)]))
            for note in entry.get("notes", []):
                parent.addChild(QTreeWidgetItem(["note", note]))
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)
        self.controller.browser_count = len(rows)
