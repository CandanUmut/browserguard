"""The waiting period that sits between deciding to loosen protection and it happening.

The rules, in full:

* Making protection **stronger** applies immediately. No wait, no passcode.
* Making protection **weaker** becomes a pending change that applies on its own
  once the cooldown has elapsed.
* The passcode only skips that wait.
* A pending change can always be cancelled, which is itself a tightening.

Nothing is ever permanently locked. If the passcode is lost, waiting still works,
so the user can never be shut out of their own machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from browserguard.core.config import AppConfig, ProtectionSettings, strictness_score


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass
class PendingChange:
    """A loosening change waiting for its cooldown to elapse."""

    requested_at: str
    apply_at: str
    settings: dict[str, Any]
    summary: str = ""

    @property
    def apply_time(self) -> datetime:
        return _parse(self.apply_at)

    @property
    def requested_time(self) -> datetime:
        return _parse(self.requested_at)

    def remaining(self, now: datetime | None = None) -> timedelta:
        delta = self.apply_time - (now or _now())
        return delta if delta.total_seconds() > 0 else timedelta(0)

    def is_due(self, now: datetime | None = None) -> bool:
        return (now or _now()) >= self.apply_time

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_at": self.requested_at,
            "apply_at": self.apply_at,
            "settings": self.settings,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingChange:
        return cls(
            requested_at=data["requested_at"],
            apply_at=data["apply_at"],
            settings=data.get("settings", {}),
            summary=data.get("summary", ""),
        )


def is_loosening(current: ProtectionSettings, proposed: ProtectionSettings) -> bool:
    """True when the proposed settings are less restrictive than the current ones."""
    return strictness_score(proposed) < strictness_score(current)


def describe_change(current: ProtectionSettings, proposed: ProtectionSettings) -> str:
    """A short, human description of what is changing."""
    parts: list[str] = []
    if current.enabled and not proposed.enabled:
        parts.append("protection turned off")
    elif not current.enabled and proposed.enabled:
        parts.append("protection turned on")
    if current.level != proposed.level:
        parts.append(f"level {current.level} to {proposed.level}")

    removed = [c for c in current.blocked_categories if c not in proposed.blocked_categories]
    added = [c for c in proposed.blocked_categories if c not in current.blocked_categories]
    if removed:
        parts.append("unblocked " + ", ".join(removed))
    if added:
        parts.append("blocked " + ", ".join(added))

    new_allowed = [a for a in proposed.allowed if a not in current.allowed]
    if new_allowed:
        parts.append("allowed " + ", ".join(new_allowed[:3]) + ("..." if len(new_allowed) > 3 else ""))

    for label, attr in (
        ("SafeSearch", "safe_search"),
        ("SafeSites", "safe_sites"),
        ("private browsing block", "block_incognito"),
        ("developer tools block", "block_devtools"),
        ("guest profile block", "block_guest_mode"),
        ("encrypted DNS block", "force_plain_dns"),
        ("extension lockdown", "lock_extensions"),
    ):
        before, after = getattr(current, attr), getattr(proposed, attr)
        if before and not after:
            parts.append(f"{label} off")
        elif after and not before:
            parts.append(f"{label} on")

    if current.youtube_restrict != proposed.youtube_restrict:
        parts.append(f"YouTube restriction {proposed.youtube_restrict}")

    return "; ".join(parts) if parts else "settings adjusted"


@dataclass
class ChangeResult:
    """What happened when a change was requested."""

    applied: bool
    pending: PendingChange | None
    message: str


def request_change(
    config: AppConfig,
    proposed: ProtectionSettings,
    passcode_ok: bool = False,
    now: datetime | None = None,
) -> tuple[AppConfig, ChangeResult]:
    """Apply a settings change immediately, or queue it behind the cooldown.

    Returns the updated config and a description of what happened. The caller is
    responsible for saving the config and pushing policy to the browsers.
    """
    now = now or _now()
    updated = config.copy()
    current = config.protection
    summary = describe_change(current, proposed)

    loosening = is_loosening(current, proposed)
    cooldown_hours = config.security.cooldown_hours

    if not loosening:
        updated.protection = proposed
        updated.pending = None
        return updated, ChangeResult(True, None, f"Applied now ({summary}).")

    if passcode_ok:
        updated.protection = proposed
        updated.pending = None
        return updated, ChangeResult(
            True, None, f"Passcode accepted, applied now ({summary})."
        )

    if cooldown_hours <= 0:
        updated.protection = proposed
        updated.pending = None
        return updated, ChangeResult(
            True, None, f"Applied now, no waiting period set ({summary})."
        )

    apply_at = now + timedelta(hours=cooldown_hours)
    pending = PendingChange(
        requested_at=now.isoformat(),
        apply_at=apply_at.isoformat(),
        settings=proposed.to_dict(),
        summary=summary,
    )
    updated.pending = pending.to_dict()
    return updated, ChangeResult(
        False,
        pending,
        f"Scheduled for {_format_delta(timedelta(hours=cooldown_hours))} from now ({summary}). "
        "Enter the passcode to apply it immediately.",
    )


def cancel_pending(config: AppConfig) -> tuple[AppConfig, ChangeResult]:
    """Drop a pending change. Always allowed, since cancelling only tightens."""
    updated = config.copy()
    if not updated.pending:
        return updated, ChangeResult(False, None, "There is no pending change.")
    updated.pending = None
    return updated, ChangeResult(False, None, "Pending change cancelled.")


def get_pending(config: AppConfig) -> PendingChange | None:
    if not config.pending:
        return None
    try:
        return PendingChange.from_dict(config.pending)
    except (KeyError, TypeError):
        return None


def promote_due_change(
    config: AppConfig, now: datetime | None = None
) -> tuple[AppConfig, bool]:
    """Apply a pending change if its time has come.

    Called on startup and by the background task, so a waiting change lands even
    if nobody opens the app.
    """
    pending = get_pending(config)
    if pending is None or not pending.is_due(now):
        return config, False
    updated = config.copy()
    updated.protection = ProtectionSettings.from_dict(pending.settings)
    updated.pending = None
    return updated, True


def _format_delta(delta: timedelta) -> str:
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 60:
        return f"{total_minutes} min"
    hours, minutes = divmod(total_minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, rem_hours = divmod(hours, 24)
    return f"{days}d {rem_hours}h" if rem_hours else f"{days}d"


def format_remaining(pending: PendingChange, now: datetime | None = None) -> str:
    """Human-readable time left on a pending change."""
    remaining = pending.remaining(now)
    if remaining.total_seconds() <= 0:
        return "ready to apply"
    return _format_delta(remaining) + " left"
