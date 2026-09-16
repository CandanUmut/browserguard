"""Ties the pieces together: config in, browser policy out."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from browserguard.core import policies, schedules as sched
from browserguard.core.browsers import DetectedBrowser, all_policy_targets
from browserguard.core.config import AppConfig, ProtectionSettings, save_config
from browserguard.core.cooldown import promote_due_change
from browserguard.core.registry import Registry, default_registry, is_admin


@dataclass
class BrowserResult:
    """Outcome of writing policy for one browser."""

    name: str
    policy_key: str
    installed: bool
    detected_via: str
    values_written: int
    error: str = ""


@dataclass
class ApplyReport:
    """Outcome of a full apply run."""

    results: list[BrowserResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    active_schedules: list[str] = field(default_factory=list)
    protection_enabled: bool = True
    promoted_pending: bool = False

    @property
    def ok(self) -> bool:
        return all(not r.error for r in self.results)

    @property
    def browsers_covered(self) -> int:
        return sum(1 for r in self.results if not r.error)

    def summary(self) -> str:
        if not self.protection_enabled:
            return f"Protection off. Policy removed from {self.browsers_covered} browser keys."
        installed = sum(1 for r in self.results if r.installed and not r.error)
        return (
            f"Protection applied to {self.browsers_covered} policy keys "
            f"({installed} installed browsers)."
        )


def resolve_settings(config: AppConfig, now: datetime | None = None) -> ProtectionSettings:
    """The settings actually in force right now, schedules included."""
    schedule_objects = sched.load_schedules(config.schedules)
    return sched.effective_settings(config.protection, schedule_objects, now)


def apply_protection(
    config: AppConfig,
    registry: Registry | None = None,
    deep_scan: bool = True,
    now: datetime | None = None,
    targets: list[DetectedBrowser] | None = None,
) -> ApplyReport:
    """Write the current effective policy to every browser on the machine."""
    registry = registry or default_registry()
    report = ApplyReport()

    settings = resolve_settings(config, now)
    report.protection_enabled = settings.enabled

    schedule_objects = sched.load_schedules(config.schedules)
    report.active_schedules = [s.name for s in sched.active_schedules(schedule_objects, now)]

    browsers = targets if targets is not None else all_policy_targets(deep_scan=deep_scan)
    seen_warnings: set[str] = set()

    for browser in browsers:
        try:
            if not settings.enabled:
                policies.clear_policies(registry, browser.policy_key)
                report.results.append(
                    BrowserResult(
                        name=browser.name,
                        policy_key=browser.policy_key,
                        installed=browser.installed,
                        detected_via=browser.detected_via,
                        values_written=0,
                    )
                )
                continue

            plan = policies.build_plan(settings, browser)
            policies.apply_plan(registry, plan)
            for warning in plan.warnings:
                if warning not in seen_warnings:
                    seen_warnings.add(warning)
                    report.warnings.append(warning)
            report.results.append(
                BrowserResult(
                    name=browser.name,
                    policy_key=browser.policy_key,
                    installed=browser.installed,
                    detected_via=browser.detected_via,
                    values_written=plan.value_count(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one browser failing must not stop the rest
            report.results.append(
                BrowserResult(
                    name=browser.name,
                    policy_key=browser.policy_key,
                    installed=browser.installed,
                    detected_via=browser.detected_via,
                    values_written=0,
                    error=str(exc),
                )
            )
    return report


def sync(
    config: AppConfig,
    registry: Registry | None = None,
    deep_scan: bool = True,
    now: datetime | None = None,
    persist: bool = True,
) -> tuple[AppConfig, ApplyReport]:
    """Promote any due pending change, apply policy, and save.

    This is the single entry point used by the GUI, the CLI and the background
    task, so a waiting change lands even if nobody opens the app.
    """
    config, promoted = promote_due_change(config, now)
    report = apply_protection(config, registry=registry, deep_scan=deep_scan, now=now)
    report.promoted_pending = promoted

    if persist:
        config.last_applied = (now or datetime.now(timezone.utc)).isoformat()
        try:
            save_config(config)
        except Exception as exc:  # noqa: BLE001 - surface but do not crash
            report.warnings.append(f"Could not save configuration: {exc}")
    return config, report


def uninstall(registry: Registry | None = None, deep_scan: bool = True) -> ApplyReport:
    """Remove every policy value BrowserGuard manages, leaving others alone."""
    registry = registry or default_registry()
    report = ApplyReport(protection_enabled=False)
    for browser in all_policy_targets(deep_scan=deep_scan):
        try:
            policies.clear_policies(registry, browser.policy_key)
            report.results.append(
                BrowserResult(
                    name=browser.name,
                    policy_key=browser.policy_key,
                    installed=browser.installed,
                    detected_via=browser.detected_via,
                    values_written=0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            report.results.append(
                BrowserResult(
                    name=browser.name,
                    policy_key=browser.policy_key,
                    installed=browser.installed,
                    detected_via=browser.detected_via,
                    values_written=0,
                    error=str(exc),
                )
            )
    return report


def verify(registry: Registry | None = None, deep_scan: bool = True) -> list[dict]:
    """Read back what is actually live, for the Verify view."""
    registry = registry or default_registry()
    rows = []
    for browser in all_policy_targets(deep_scan=deep_scan):
        applied = policies.read_applied(registry, browser.policy_key)
        rows.append(
            {
                "name": browser.name,
                "policy_key": browser.policy_key,
                "installed": browser.installed,
                "detected_via": browser.detected_via,
                "notes": browser.notes,
                "applied": applied,
                "blocked_count": len(applied.get("URLBlocklist", []) or [])
                or len(applied.get("WebsiteFilter\\Block", []) or []),
            }
        )
    return rows


def requires_admin() -> bool:
    """Whether the process still needs elevation to write policy."""
    return not is_admin()
