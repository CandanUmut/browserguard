"""The five pages of the interface.

Every page is built to fit the window without scrolling, so nothing important
ends up below the fold.
"""

from __future__ import annotations

import socket
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTime, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTimeEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from browserguard.core import blocklists, cooldown, engine, scheduler
from browserguard.core.config import (
    COOLDOWN_CHOICES,
    LEVEL_DESCRIPTIONS,
    LEVEL_LIGHT,
    LEVEL_MODERATE,
    LEVEL_OFF,
    LEVEL_STRICT,
    format_cooldown,
    preset,
)
from browserguard.core.passcode import export_passcode, generate_passcode, hash_passcode
from browserguard.core.schedules import DAY_NAMES, Schedule, load_schedules, next_transition
from browserguard.gui.theme import COLORS
from browserguard.gui.widgets import Card, ChoiceCard, PageHeader, dim, link, row


class Page(QWidget):
    """Base page: a column of cards sized to fit the window."""

    def __init__(self, controller, title: str, subtitle: str):
        super().__init__()
        self.controller = controller
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(26, 18, 26, 20)
        self.column.setSpacing(13)
        self.column.addWidget(PageHeader(title, subtitle))

    def refresh(self) -> None:
        """Called when the page becomes visible."""


# ---------------------------------------------------------------------------
# Shared: the site list editor, used for both blocked and allowed sites
# ---------------------------------------------------------------------------


class SiteListEditor(QWidget):
    """Type a site, press Enter, done. Select a row and press Delete to remove."""

    changed = Signal(list)

    def __init__(self, placeholder: str, empty_text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._sites: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        entry = QHBoxLayout()
        entry.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.returnPressed.connect(self._add)
        self.input.textChanged.connect(self._update_add_state)
        entry.addWidget(self.input, 1)

        self.add_button = QPushButton("Add")
        self.add_button.setObjectName("Primary")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._add)
        entry.addWidget(self.add_button)
        layout.addLayout(entry)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._update_remove_state)
        layout.addWidget(self.list_widget, 1)

        QShortcut(QKeySequence(Qt.Key_Delete), self.list_widget, self._remove)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.count_label = dim(empty_text)
        self._empty_text = empty_text
        footer.addWidget(self.count_label, 1)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._remove)
        footer.addWidget(self.remove_button)
        layout.addLayout(footer)

    def set_sites(self, sites: list[str]) -> None:
        self._sites = list(sites)
        self.list_widget.clear()
        self.list_widget.addItems(self._sites)
        self._update_count()
        self._update_remove_state()

    def sites(self) -> list[str]:
        return list(self._sites)

    def _update_add_state(self, text: str) -> None:
        self.add_button.setEnabled(bool(blocklists.normalise_pattern(text)))

    def _update_remove_state(self) -> None:
        self.remove_button.setEnabled(bool(self.list_widget.selectedItems()))

    def _update_count(self) -> None:
        count = len(self._sites)
        self.count_label.setText(
            self._empty_text if not count else f"{count} site{'s' if count != 1 else ''} in this list"
        )

    def _add(self) -> None:
        pattern = blocklists.normalise_pattern(self.input.text())
        if not pattern:
            return
        if pattern in self._sites:
            self.input.clear()
            self._flash(f"{pattern} is already in the list")
            return
        self._sites.append(pattern)
        self.input.clear()
        self.set_sites(self._sites)
        self.changed.emit(self.sites())

    def _remove(self) -> None:
        selected = {item.text() for item in self.list_widget.selectedItems()}
        if not selected:
            return
        self._sites = [s for s in self._sites if s not in selected]
        self.set_sites(self._sites)
        self.changed.emit(self.sites())

    def _flash(self, message: str) -> None:
        self.count_label.setText(message)


# ---------------------------------------------------------------------------
# Protection
# ---------------------------------------------------------------------------


class DashboardPage(Page):
    LEVELS = (
        (LEVEL_OFF, "Off"),
        (LEVEL_LIGHT, "Light"),
        (LEVEL_MODERATE, "Moderate"),
        (LEVEL_STRICT, "Strict"),
    )

    OPTIONS = (
        ("safe_search", "Force SafeSearch", "Google and Bing return filtered results only."),
        (
            "safe_sites",
            "Adult content filter",
            "Chrome classifies pages as they load, so this catches adult sites that "
            "are on no blocklist.",
        ),
        (
            "force_plain_dns",
            "Block the browser's encrypted DNS",
            "The browser's own DoH resolves names past any DNS filter on this "
            "machine or your router. This is the one people miss.",
        ),
        ("block_incognito", "Block private browsing", "No incognito or private windows."),
        (
            "block_devtools",
            "Block developer tools",
            "Without this, F12 can be used to edit the page and inspect requests.",
        ),
        ("block_guest_mode", "Block guest profiles", "A guest profile starts with no policy."),
        (
            "lock_extensions",
            "Block new extensions",
            "Stops new installs. Extensions already installed keep working.",
        ),
    )

    def __init__(self, controller):
        super().__init__(
            controller,
            "Protection",
            "Stronger settings apply straight away. Weaker ones may wait, "
            "depending on your settings.",
        )

        status = Card()
        status.body().setSpacing(3)
        self.status_label = QLabel("...")
        self.status_label.setObjectName("StatusBig")
        status.add(self.status_label)
        self.status_detail = dim("")
        status.add(self.status_detail)
        self.column.addWidget(status)

        level_card = Card("How strict should it be?")
        level_row = QHBoxLayout()
        level_row.setSpacing(9)
        self.level_cards: dict[str, ChoiceCard] = {}
        for level_id, label in self.LEVELS:
            choice = ChoiceCard(label, LEVEL_DESCRIPTIONS[level_id])
            choice.setMinimumHeight(104)
            choice.clicked.connect(lambda l=level_id: self._pick_level(l))
            self.level_cards[level_id] = choice
            level_row.addWidget(choice, 1)
        level_card.add_layout(level_row)
        self.column.addWidget(level_card)

        options_card = Card(
            "Extra options",
            "Hover any option for what it does. Changing one switches the level to Custom.",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(2)
        self.toggles: dict[str, QCheckBox] = {}
        for index, (attr, label, hint) in enumerate(self.OPTIONS):
            box = QCheckBox(label)
            box.setToolTip(hint)
            box.toggled.connect(lambda checked, a=attr: self._toggle(a, checked))
            self.toggles[attr] = box
            grid.addWidget(box, index % 4, index // 4)

        youtube_row = QWidget()
        youtube_layout = QHBoxLayout(youtube_row)
        youtube_layout.setContentsMargins(0, 0, 0, 0)
        youtube_layout.setSpacing(8)
        youtube_label = QLabel("YouTube Restricted Mode")
        youtube_label.setToolTip(
            "Restricted Mode hides every YouTube comment and blocks most live "
            "streams. It is off by default because that surprises people."
        )
        youtube_layout.addWidget(youtube_label)
        self.youtube = QComboBox()
        self.youtube.addItems(["off", "moderate", "strict"])
        self.youtube.setFixedWidth(120)
        self.youtube.currentTextChanged.connect(self._set_youtube)
        youtube_layout.addWidget(self.youtube)
        youtube_layout.addStretch(1)
        grid.addWidget(youtube_row, 3, 1)
        options_card.add_layout(grid)
        self.column.addWidget(options_card)
        self.column.addStretch(1)

    def _pick_level(self, level: str) -> None:
        draft = preset(level)
        draft.custom_blocked = self.controller.draft.custom_blocked
        draft.allowed = self.controller.draft.allowed
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
            self.status_label.setStyleSheet(f"color: {COLORS['good']}; background: transparent;")
        else:
            self.status_label.setText("Not protected")
            self.status_label.setStyleSheet(f"color: {COLORS['bad']}; background: transparent;")

        blocked = len(blocklists.expand_categories(live.blocked_categories)) + len(
            live.custom_blocked
        )
        schedules = load_schedules(self.controller.config.schedules)
        wait = format_cooldown(self.controller.config.security.cooldown_hours)
        self.status_detail.setText(
            f"Level {live.level}  ·  {blocked} sites blocked  ·  "
            f"{self.controller.browser_count or 'all'} browsers covered  ·  "
            f"{next_transition(schedules)}  ·  {wait}"
        )

        for level_id, choice in self.level_cards.items():
            choice.set_selected(draft.level == level_id)

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
            "Tick the categories to block, then add your own sites underneath.",
        )

        category_card = Card(
            "Categories",
            "Bundled lists, stored inside the app, so they work with no internet connection.",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(2)
        self.category_boxes: dict[str, QCheckBox] = {}
        for index, category in enumerate(blocklists.CATEGORIES):
            box = QCheckBox(f"{category.name}  ({blocklists.category_size(category.id)})")
            box.setToolTip(category.description)
            box.toggled.connect(lambda checked, c=category.id: self._toggle_category(c, checked))
            self.category_boxes[category.id] = box
            grid.addWidget(box, index % 4, index // 4)
        category_card.add_layout(grid)
        self.column.addWidget(category_card)

        lists_row = QHBoxLayout()
        lists_row.setSpacing(13)

        blocked_card = Card("Blocked sites", "Your own entries, on top of the categories above.")
        self.blocked_editor = SiteListEditor(
            "Type a website and press Enter, e.g. example.com",
            "Nothing added yet.",
        )
        self.blocked_editor.changed.connect(self._blocked_changed)
        blocked_card.add(self.blocked_editor)
        lists_row.addWidget(blocked_card, 1)

        allowed_card = Card(
            "Always allowed",
            "Exceptions that beat the blocklist, for a site caught by mistake.",
        )
        self.allowed_editor = SiteListEditor(
            "Type a website and press Enter, e.g. school.edu",
            "Nothing added yet.",
        )
        self.allowed_editor.changed.connect(self._allowed_changed)
        allowed_card.add(self.allowed_editor)
        self.allowlist_only = QCheckBox("Block everything except the sites listed here")
        self.allowlist_only.setToolTip(
            "The strictest possible setting. With an empty list the browser cannot "
            "reach anything at all."
        )
        self.allowlist_only.toggled.connect(self._toggle_allowlist_only)
        allowed_card.add(self.allowlist_only)
        lists_row.addWidget(allowed_card, 1)

        self.column.addLayout(lists_row, 1)

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

    def _blocked_changed(self, sites: list) -> None:
        self.controller.set_draft(replace(self.controller.draft, custom_blocked=list(sites)))

    def _allowed_changed(self, sites: list) -> None:
        self.controller.set_draft(replace(self.controller.draft, allowed=list(sites)))

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
        if self.blocked_editor.sites() != draft.custom_blocked:
            self.blocked_editor.set_sites(draft.custom_blocked)
        if self.allowed_editor.sites() != draft.allowed:
            self.allowed_editor.set_sites(draft.allowed)
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
        self.setMinimumWidth(460)
        self.schedule = schedule

        layout = QVBoxLayout(self)
        layout.setSpacing(11)

        layout.addWidget(QLabel("Name"))
        self.name = QLineEdit(schedule.name)
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
            dim("Ending earlier than it starts makes it overnight, e.g. 22:00 until 06:00.")
        )

        layout.addWidget(QLabel("Block these during the window"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(22)
        self.category_boxes: dict[str, QCheckBox] = {}
        for index, category in enumerate(blocklists.CATEGORIES):
            box = QCheckBox(category.name)
            box.setChecked(category.id in schedule.categories)
            self.category_boxes[category.id] = box
            grid.addWidget(box, index % 4, index // 4)
        layout.addLayout(grid)

        layout.addWidget(QLabel("Extra sites (comma separated)"))
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
            "Add restrictions during set hours, such as blocking social media "
            "during school time. A schedule can only add restrictions, never remove one.",
        )

        card = Card("Your schedules")
        self.list_widget = QListWidget()
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
        buttons = row(add_button, edit_button, delete_button)
        buttons.addStretch(1)
        card.add_layout(buttons)
        self.column.addWidget(card, 1)

        self.background_note = dim("")
        self.column.addWidget(self.background_note)

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

    def _edit(self) -> None:
        index = self.list_widget.currentRow()
        schedules = self._schedules()
        if not 0 <= index < len(schedules):
            return
        dialog = ScheduleDialog(schedules[index], self)
        if dialog.exec() == QDialog.Accepted:
            schedules[index] = dialog.result_schedule()
            self._save(schedules)

    def _delete(self) -> None:
        index = self.list_widget.currentRow()
        schedules = self._schedules()
        if not 0 <= index < len(schedules):
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
        schedules = self._schedules()
        for schedule in schedules:
            item = QListWidgetItem(f"{schedule.name}   ·   {schedule.describe()}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if schedule.enabled else Qt.Unchecked)
            self.list_widget.addItem(item)
        if not schedules:
            placeholder = QListWidgetItem("No schedules yet. Add one to get started.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(placeholder)
        self.list_widget.blockSignals(False)

        if schedules and not scheduler.is_registered():
            self.background_note.setText(
                "Schedules need the background task to switch policy on time. "
                "Turn it on under Security."
            )
        else:
            self.background_note.setText("")


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class PasscodeDialog(QDialog):
    """Shows a newly generated passcode with copy and save actions."""

    def __init__(self, code: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Your passcode")
        self.setMinimumWidth(460)
        self.code = code
        self.saved_to: Path | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(13)

        heading = QLabel("Here is your passcode")
        heading.setObjectName("WizardTitle")
        layout.addWidget(heading)

        code_label = QLabel(code)
        code_label.setAlignment(Qt.AlignCenter)
        code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        code_label.setStyleSheet(
            f"font-size: 27px; font-weight: 700; letter-spacing: 3px;"
            f" padding: 18px; border-radius: 10px;"
            f" background: {COLORS['accent_soft']}; color: {COLORS['accent_dim']};"
        )
        layout.addWidget(code_label)

        layout.addWidget(
            dim(
                "This is the only time it is shown. It is only ever needed to skip "
                "the waiting period - never to open BrowserGuard or to make "
                "protection stronger. If you lose it, nothing is locked: changes "
                "still apply once the wait is over."
            )
        )

        actions = QHBoxLayout()
        actions.setSpacing(8)
        copy_button = QPushButton("Copy to clipboard")
        copy_button.clicked.connect(self._copy)
        actions.addWidget(copy_button)
        save_button = QPushButton("Save to a file")
        save_button.clicked.connect(self._save)
        actions.addWidget(save_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.status = dim("")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.code)
        self.status.setText("Copied to the clipboard.")

    def _save(self) -> None:
        default = str(Path.home() / "BrowserGuard-passcode.txt")
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save passcode", default, "Text files (*.txt)"
        )
        if not destination:
            return
        export_passcode(self.code, Path(destination), machine_name=socket.gethostname())
        self.saved_to = Path(destination)
        self.status.setText(f"Saved to {destination}")


class SecurityPage(Page):
    def __init__(self, controller):
        super().__init__(
            controller,
            "Waiting period",
            "An optional delay before protection can be reduced, so a change has "
            "to be deliberate rather than impulsive.",
        )

        wait_card = Card("How long should a reduction have to wait?")
        choices_row = QHBoxLayout()
        choices_row.setSpacing(9)
        self.cooldown_cards: dict[float, ChoiceCard] = {}
        for hours, label in COOLDOWN_CHOICES:
            title = "Off" if hours <= 0 else format_cooldown(hours).replace(" (suggested)", "")
            description = label.split(" - ")[-1] if " - " in label else label
            if hours == 0.25:
                description = "Suggested. Long enough to outlast an impulse."
            elif hours <= 0:
                description = "Every change applies straight away."
            else:
                description = f"A reduction waits {format_cooldown(hours)} before it applies."
            choice = ChoiceCard(title, description)
            choice.setMinimumHeight(96)
            choice.clicked.connect(lambda h=hours: self._set_cooldown(h))
            self.cooldown_cards[hours] = choice
            choices_row.addWidget(choice, 1)
        wait_card.add_layout(choices_row)
        self.column.addWidget(wait_card)

        passcode_card = Card(
            "Passcode",
            "Optional, and only useful alongside a waiting period: it is the way "
            "to skip the wait.",
        )
        self.passcode_status = dim("")
        passcode_card.add(self.passcode_status)
        passcode_row = QHBoxLayout()
        passcode_row.setSpacing(8)
        self.passcode_button = QPushButton("Create a passcode")
        self.passcode_button.setObjectName("Primary")
        self.passcode_button.clicked.connect(self._generate_passcode)
        passcode_row.addWidget(self.passcode_button)
        self.remove_passcode_button = QPushButton("Remove passcode")
        self.remove_passcode_button.clicked.connect(self._remove_passcode)
        passcode_row.addWidget(self.remove_passcode_button)
        passcode_row.addStretch(1)
        passcode_card.add_layout(passcode_row)
        self.column.addWidget(passcode_card)

        background_card = Card(
            "Background task",
            "Needed for schedules, and it lets a waiting change apply even if this "
            "app is closed. Visible in Task Scheduler as 'BrowserGuard Sync'.",
        )
        self.background_status = dim("")
        background_card.add(self.background_status)
        self.background_button = QPushButton("")
        self.background_button.clicked.connect(self._toggle_background)
        background_row = row(self.background_button)
        background_row.addStretch(1)
        background_card.add_layout(background_row)
        self.column.addWidget(background_card)

        self.column.addStretch(1)

        remove_row = QHBoxLayout()
        remove_row.addWidget(
            dim("Turning everything off removes all policy and the background task.")
        )
        remove_row.addStretch(1)
        remove_button = QPushButton("Turn off all protection")
        remove_button.setObjectName("Danger")
        remove_button.clicked.connect(self._uninstall)
        remove_row.addWidget(remove_button)
        self.column.addLayout(remove_row)

    def _set_cooldown(self, hours: float) -> None:
        old = self.controller.config.security.cooldown_hours
        if hours == old:
            return
        if hours < old:
            if self.controller.config.security.has_passcode:
                passcode, ok = QInputDialog.getText(
                    self,
                    "Passcode required",
                    f"Shortening the wait from {format_cooldown(old)} to "
                    f"{format_cooldown(hours)} reduces protection.\n\n"
                    "Enter the passcode, or cancel and change it after the current "
                    "period has passed.",
                )
                if not ok:
                    self.refresh()
                    return
                if not self.controller.check_passcode(passcode):
                    QMessageBox.warning(self, "Passcode", "That passcode was not correct.")
                    self.refresh()
                    return
        self.controller.set_cooldown(hours)
        self.refresh()

    def _generate_passcode(self) -> None:
        code = generate_passcode()
        digest, salt = hash_passcode(code)
        self.controller.set_passcode(digest, salt)
        PasscodeDialog(code, self).exec()
        self.refresh()

    def _remove_passcode(self) -> None:
        if not self.controller.config.security.has_passcode:
            return
        passcode, ok = QInputDialog.getText(
            self, "Passcode", "Enter the current passcode to remove it:"
        )
        if not ok:
            return
        if not self.controller.check_passcode(passcode):
            QMessageBox.warning(self, "Passcode", "That passcode was not correct.")
            return
        self.controller.set_passcode("", "")
        QMessageBox.information(self, "Passcode removed", "There is no passcode now.")
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
                "Turn off all protection",
                "Remove every policy BrowserGuard wrote?\n\nIf a waiting period is "
                "set, this goes through it unless you enter the passcode.",
            )
            != QMessageBox.Yes
        ):
            return
        self.controller.request_uninstall(self)

    def refresh(self) -> None:
        security = self.controller.config.security
        for hours, choice in self.cooldown_cards.items():
            choice.set_selected(abs(security.cooldown_hours - hours) < 1e-6)

        if security.has_passcode:
            self.passcode_status.setText("A passcode is set.")
            self.passcode_button.setText("Replace passcode")
            self.remove_passcode_button.setVisible(True)
        else:
            self.passcode_status.setText(
                "No passcode set."
                if security.cooldown_hours > 0
                else "No passcode set. With no waiting period, a passcode has nothing to skip."
            )
            self.passcode_button.setText("Create a passcode")
            self.remove_passcode_button.setVisible(False)

        registered = scheduler.is_registered()
        self.background_status.setText("Running every 5 minutes." if registered else "Not set up.")
        self.background_button.setText("Turn off" if registered else "Turn on")


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
            "What is written right now, read back browser by browser. "
            "Cross-check it in the browser itself at chrome://policy.",
        )

        card = Card()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Browser / policy", "Value"])
        self.tree.setColumnWidth(0, 360)
        card.add(self.tree)
        self.refresh_button = QPushButton("Rescan")
        self.refresh_button.setObjectName("Primary")
        self.refresh_button.clicked.connect(self.refresh)
        buttons = row(self.refresh_button)
        buttons.addStretch(1)
        card.add_layout(buttons)
        self.column.addWidget(card, 1)
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
                parent.addChild(QTreeWidgetItem(["no policy applied", ""]))
            for name, value in sorted(applied.items()):
                if isinstance(value, list):
                    node = QTreeWidgetItem([name, f"{len(value)} entries"])
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
            parent.setExpanded(False)
        self.controller.browser_count = len(rows)
