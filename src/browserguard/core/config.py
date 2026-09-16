"""Protection settings, presets, and on-disk configuration.

Configuration lives in ProgramData rather than a user profile, because the
policy it describes is machine-wide and writing it already needs administrator
rights. The file is plain JSON and safe to read, copy between machines, or keep
in version control.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from browserguard.core.errors import ConfigError

LEVEL_OFF = "off"
LEVEL_LIGHT = "light"
LEVEL_MODERATE = "moderate"
LEVEL_STRICT = "strict"
LEVEL_CUSTOM = "custom"

LEVELS = (LEVEL_OFF, LEVEL_LIGHT, LEVEL_MODERATE, LEVEL_STRICT, LEVEL_CUSTOM)

LEVEL_DESCRIPTIONS = {
    LEVEL_OFF: "No policy applied. Browsers behave normally.",
    LEVEL_LIGHT: "Adult and proxy sites blocked, SafeSearch on. Everything else untouched.",
    LEVEL_MODERATE: "Light, plus gambling and dating, no private browsing, no developer tools.",
    LEVEL_STRICT: "Moderate, plus social, gaming, guest profiles off and extensions locked.",
    LEVEL_CUSTOM: "Your own combination of settings.",
}


@dataclass
class ProtectionSettings:
    """What protection should be in force."""

    enabled: bool = True
    level: str = LEVEL_MODERATE
    blocked_categories: list[str] = field(default_factory=lambda: ["adult", "proxy"])
    custom_blocked: list[str] = field(default_factory=list)
    allowed: list[str] = field(default_factory=list)
    allowlist_only: bool = False
    safe_search: bool = True
    # Default off on purpose: Restricted Mode hides all YouTube comments and
    # blocks most live streams, which surprises people who did not ask for it.
    youtube_restrict: str = "off"
    safe_sites: bool = True
    block_incognito: bool = True
    block_devtools: bool = True
    block_guest_mode: bool = False
    force_plain_dns: bool = True
    lock_extensions: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProtectionSettings:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def preset(level: str) -> ProtectionSettings:
    """Return the settings for a named protection level."""
    if level == LEVEL_OFF:
        return ProtectionSettings(
            enabled=False,
            level=LEVEL_OFF,
            blocked_categories=[],
            safe_search=False,
            safe_sites=False,
            block_incognito=False,
            block_devtools=False,
            block_guest_mode=False,
            force_plain_dns=False,
        )
    if level == LEVEL_LIGHT:
        return ProtectionSettings(
            level=LEVEL_LIGHT,
            blocked_categories=["adult", "proxy"],
            safe_search=True,
            safe_sites=True,
            block_incognito=False,
            block_devtools=False,
            block_guest_mode=False,
            force_plain_dns=True,
        )
    if level == LEVEL_MODERATE:
        return ProtectionSettings(
            level=LEVEL_MODERATE,
            blocked_categories=["adult", "proxy", "gambling", "dating"],
            safe_search=True,
            safe_sites=True,
            block_incognito=True,
            block_devtools=True,
            block_guest_mode=True,
            force_plain_dns=True,
        )
    if level == LEVEL_STRICT:
        return ProtectionSettings(
            level=LEVEL_STRICT,
            blocked_categories=[
                "adult",
                "proxy",
                "gambling",
                "dating",
                "social",
                "gaming",
            ],
            safe_search=True,
            safe_sites=True,
            block_incognito=True,
            block_devtools=True,
            block_guest_mode=True,
            force_plain_dns=True,
            lock_extensions=True,
        )
    raise ValueError(f"Unknown protection level: {level}")


# Ordering used to decide whether a change tightens or loosens protection.
_LEVEL_RANK = {
    LEVEL_OFF: 0,
    LEVEL_LIGHT: 1,
    LEVEL_CUSTOM: 2,
    LEVEL_MODERATE: 2,
    LEVEL_STRICT: 3,
}


def strictness_score(settings: ProtectionSettings) -> int:
    """A rough measure of how restrictive a configuration is.

    Used only to decide whether a proposed change needs to wait out the cooldown.
    Anything that reduces the score is treated as loosening.
    """
    if not settings.enabled:
        return 0
    score = 10 * _LEVEL_RANK.get(settings.level, 2)
    score += 5 * len(settings.blocked_categories)
    score += len(settings.custom_blocked)
    score -= len(settings.allowed)
    score += 40 if settings.allowlist_only else 0
    score += 3 if settings.safe_search else 0
    score += 3 if settings.safe_sites else 0
    score += {"off": 0, "moderate": 2, "strict": 4}.get(settings.youtube_restrict, 0)
    score += 4 if settings.block_incognito else 0
    score += 4 if settings.block_devtools else 0
    score += 2 if settings.block_guest_mode else 0
    score += 3 if settings.force_plain_dns else 0
    score += 2 if settings.lock_extensions else 0
    return score


@dataclass
class SecuritySettings:
    """Cooldown and passcode configuration."""

    cooldown_hours: float = 24.0
    passcode_hash: str = ""
    passcode_salt: str = ""
    passcode_created_at: str = ""

    @property
    def has_passcode(self) -> bool:
        return bool(self.passcode_hash and self.passcode_salt)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecuritySettings:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AppConfig:
    """The whole persisted state of the application."""

    version: int = 1
    # A fresh install starts at Moderate, matching the preset of the same name.
    protection: ProtectionSettings = field(default_factory=lambda: preset(LEVEL_MODERATE))
    security: SecuritySettings = field(default_factory=SecuritySettings)
    schedules: list[dict[str, Any]] = field(default_factory=list)
    pending: dict[str, Any] | None = None
    last_applied: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "protection": self.protection.to_dict(),
            "security": self.security.to_dict(),
            "schedules": self.schedules,
            "pending": self.pending,
            "last_applied": self.last_applied,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        return cls(
            version=data.get("version", 1),
            protection=ProtectionSettings.from_dict(data.get("protection", {})),
            security=SecuritySettings.from_dict(data.get("security", {})),
            schedules=data.get("schedules", []),
            pending=data.get("pending"),
            last_applied=data.get("last_applied", ""),
        )

    def copy(self) -> AppConfig:
        return AppConfig.from_dict(json.loads(json.dumps(self.to_dict())))


def config_dir() -> Path:
    """Machine-wide configuration directory."""
    override = os.environ.get("BROWSERGUARD_HOME")
    if override:
        return Path(override)
    base = os.environ.get("ProgramData", "C:\\ProgramData")
    return Path(base) / "BrowserGuard"


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> AppConfig:
    """Load configuration, returning defaults when nothing is stored yet."""
    path = config_path()
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    return AppConfig.from_dict(data)


def save_config(config: AppConfig) -> Path:
    """Write configuration atomically so a crash cannot leave a truncated file."""
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        raise ConfigError(f"Could not write {path}: {exc}") from exc
    return path


def with_level(config: AppConfig, level: str) -> AppConfig:
    """Return a copy of the config switched to a preset level."""
    updated = config.copy()
    if level == LEVEL_CUSTOM:
        updated.protection = replace(updated.protection, level=LEVEL_CUSTOM)
    else:
        kept_custom = updated.protection.custom_blocked
        kept_allowed = updated.protection.allowed
        updated.protection = preset(level)
        updated.protection.custom_blocked = kept_custom
        updated.protection.allowed = kept_allowed
    return updated
