"""Command line interface.

Everything the GUI can do is available here too, which makes BrowserGuard usable
over Remote Desktop, from a script, or on a machine where the GUI will not start.
``--sync`` is what the background scheduled task runs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from browserguard.core import blocklists, cooldown, engine, scheduler
from browserguard.core.browsers import detect_browsers
from browserguard.core.config import (
    LEVELS,
    LEVEL_CUSTOM,
    LEVEL_DESCRIPTIONS,
    config_path,
    load_config,
    save_config,
    with_level,
)
from browserguard.core.errors import BrowserGuardError
from browserguard.core.passcode import (
    export_passcode,
    generate_passcode,
    hash_passcode,
    verify_passcode,
)
from browserguard.core.registry import is_admin
from browserguard.core.schedules import Schedule, load_schedules
from browserguard.version import APP_NAME, __version__


def _need_admin() -> bool:
    if is_admin():
        return False
    print("This needs administrator rights. Run the command from an elevated terminal.")
    return True


def _passcode_ok(config, supplied: str | None) -> bool:
    if not supplied:
        return False
    security = config.security
    if not security.has_passcode:
        return False
    return verify_passcode(supplied, security.passcode_hash, security.passcode_salt)


def cmd_status(args) -> int:
    config = load_config()
    settings = engine.resolve_settings(config)
    print(f"{APP_NAME} {__version__}")
    print(f"Config:      {config_path()}")
    print(f"Protection:  {'ON' if settings.enabled else 'OFF'}  (level: {settings.level})")
    print(f"Categories:  {', '.join(settings.blocked_categories) or 'none'}")
    print(f"Custom block:{len(settings.custom_blocked)} entries")
    print(f"Allowed:     {len(settings.allowed)} entries")
    print(f"SafeSearch:  {'on' if settings.safe_search else 'off'}")
    print(f"YouTube:     {settings.youtube_restrict}")
    print(f"Cooldown:    {config.security.cooldown_hours} h")
    print(f"Passcode:    {'set' if config.security.has_passcode else 'not set'}")
    print(f"Background:  {'registered' if scheduler.is_registered() else 'not registered'}")

    pending = cooldown.get_pending(config)
    if pending:
        print(
            f"\nPending change: {pending.summary}\n"
            f"  applies in {cooldown.format_remaining(pending)} "
            f"(at {pending.apply_time.astimezone():%Y-%m-%d %H:%M})"
        )
    schedules = load_schedules(config.schedules)
    if schedules:
        print("\nSchedules:")
        for item in schedules:
            mark = "on " if item.enabled else "off"
            print(f"  [{mark}] {item.name}: {item.describe()}")
    return 0


def cmd_detect(args) -> int:
    print("Browsers found on this machine:\n")
    for browser in detect_browsers(deep_scan=not args.fast):
        state = "installed" if browser.installed else browser.detected_via
        print(f"  {browser.name:<32} {browser.policy_key:<44} [{state}]")
        for note in browser.notes:
            print(f"      - {note}")
    return 0


def cmd_apply(args) -> int:
    if _need_admin():
        return 1
    config = load_config()
    config, report = engine.sync(config, deep_scan=not args.fast)
    print(report.summary())
    if report.promoted_pending:
        print("A pending change reached its scheduled time and has been applied.")
    if report.active_schedules:
        print(f"Active schedules: {', '.join(report.active_schedules)}")
    for warning in report.warnings:
        print(f"  note: {warning}")
    for result in report.results:
        if result.error:
            print(f"  FAILED {result.name}: {result.error}")
    return 0 if report.ok else 1


def cmd_level(args) -> int:
    if _need_admin():
        return 1
    if args.level not in LEVELS or args.level == LEVEL_CUSTOM:
        print(f"Pick one of: {', '.join(l for l in LEVELS if l != LEVEL_CUSTOM)}")
        return 2
    config = load_config()
    proposed = with_level(config, args.level).protection
    config, result = cooldown.request_change(
        config, proposed, passcode_ok=_passcode_ok(config, args.passcode)
    )
    save_config(config)
    print(result.message)
    if result.applied:
        _, report = engine.sync(config, deep_scan=not args.fast)
        print(report.summary())
    return 0


def _edit_list(args, attribute: str, add: bool) -> int:
    if _need_admin():
        return 1
    config = load_config()
    proposed = load_config().protection
    current = list(getattr(proposed, attribute))
    for raw in args.domains:
        pattern = blocklists.normalise_pattern(raw)
        if not pattern:
            continue
        if add and pattern not in current:
            current.append(pattern)
        elif not add and pattern in current:
            current.remove(pattern)
    setattr(proposed, attribute, current)
    proposed.level = LEVEL_CUSTOM

    config, result = cooldown.request_change(
        config, proposed, passcode_ok=_passcode_ok(config, args.passcode)
    )
    save_config(config)
    print(result.message)
    if result.applied:
        _, report = engine.sync(config)
        print(report.summary())
    return 0


def cmd_block(args) -> int:
    return _edit_list(args, "custom_blocked", add=True)


def cmd_unblock(args) -> int:
    return _edit_list(args, "custom_blocked", add=False)


def cmd_allow(args) -> int:
    return _edit_list(args, "allowed", add=True)


def cmd_categories(args) -> int:
    for category in blocklists.CATEGORIES:
        count = blocklists.category_size(category.id)
        print(f"  {category.id:<11} {count:>4} sites   {category.name}")
        print(f"              {category.description}")
    return 0


def cmd_passcode(args) -> int:
    if _need_admin():
        return 1
    config = load_config()
    code = generate_passcode()
    digest, salt = hash_passcode(code)
    config.security.passcode_hash = digest
    config.security.passcode_salt = salt
    from datetime import datetime, timezone

    config.security.passcode_created_at = datetime.now(timezone.utc).isoformat()
    save_config(config)

    destination = Path(args.out) if args.out else Path.home() / "BrowserGuard-passcode.txt"
    import socket

    export_passcode(code, destination, machine_name=socket.gethostname())
    print(f"New passcode: {code}")
    print(f"Saved to:     {destination}")
    print(
        "\nThis passcode only skips the waiting period. It is not needed to open\n"
        "BrowserGuard or to make protection stronger. Losing it locks nothing -\n"
        "changes still apply once the wait has passed."
    )
    return 0


def cmd_cooldown(args) -> int:
    if _need_admin():
        return 1
    config = load_config()
    old = config.security.cooldown_hours
    # Lengthening the wait is a tightening, so it is immediate. Shortening it is
    # a loosening and has to wait out the current cooldown.
    if args.hours < old and not _passcode_ok(config, args.passcode):
        print(
            f"Shortening the waiting period from {old}h to {args.hours}h reduces "
            "protection, so it needs the passcode. Without it, set the new value "
            "after the current period elapses."
        )
        return 1
    config.security.cooldown_hours = args.hours
    save_config(config)
    print(f"Waiting period set to {args.hours} hours.")
    return 0


def cmd_pending(args) -> int:
    config = load_config()
    pending = cooldown.get_pending(config)
    if not pending:
        print("No pending change.")
        return 0
    print(f"Pending: {pending.summary}")
    print(f"Applies: {pending.apply_time.astimezone():%Y-%m-%d %H:%M} ({cooldown.format_remaining(pending)})")
    if args.cancel:
        config, result = cooldown.cancel_pending(config)
        save_config(config)
        print(result.message)
    return 0


def cmd_verify(args) -> int:
    rows = engine.verify(deep_scan=not args.fast)
    for row in rows:
        applied = row["applied"]
        state = "installed" if row["installed"] else row["detected_via"]
        print(f"\n{row['name']}  [{state}]")
        print(f"  key: {row['policy_key']}")
        if not applied:
            print("  (no policy applied)")
            continue
        for name, value in sorted(applied.items()):
            if isinstance(value, list):
                preview = ", ".join(str(v) for v in value[:3])
                more = f" ... +{len(value) - 3} more" if len(value) > 3 else ""
                print(f"  {name}: {len(value)} entries [{preview}{more}]")
            else:
                print(f"  {name}: {value}")
    return 0


def cmd_background(args) -> int:
    if _need_admin():
        return 1
    if args.action == "install":
        ok, message = scheduler.register(args.interval)
    elif args.action == "remove":
        ok, message = scheduler.unregister()
    else:
        print(f"Background task: {'registered' if scheduler.is_registered() else 'not registered'}")
        return 0
    print(message)
    return 0 if ok else 1


def cmd_uninstall(args) -> int:
    if _need_admin():
        return 1
    config = load_config()
    pending = cooldown.get_pending(config)
    if config.protection.enabled and not _passcode_ok(config, args.passcode):
        if config.security.cooldown_hours > 0 and not args.force:
            print(
                "Removing protection is a loosening change, so it goes through the "
                "waiting period. Use --passcode to do it now, or --force to skip "
                "(which only works because you already hold administrator rights)."
            )
            if pending:
                print(f"Current pending change applies in {cooldown.format_remaining(pending)}.")
            return 1
    report = engine.uninstall(deep_scan=not args.fast)
    scheduler.unregister()
    config.protection.enabled = False
    config.pending = None
    save_config(config)
    print(f"Policy removed from {report.browsers_covered} keys. Background task removed.")
    print("Restart any open browser for the change to take effect.")
    return 0


def cmd_sync(args) -> int:
    """Used by the background task: promote due changes, reapply policy, exit."""
    try:
        config = load_config()
        config, report = engine.sync(config, deep_scan=False)
        if args.verbose:
            print(report.summary())
        return 0 if report.ok else 1
    except BrowserGuardError as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="browserguard",
        description=f"{APP_NAME} {__version__} - browser-level parental controls for Windows.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Reapply policy and promote any due change (used by the background task).",
    )
    parser.add_argument("--verbose", action="store_true", help="Print more detail.")
    parser.add_argument(
        "--fast", action="store_true", help="Skip scanning binaries for unknown browser forks."
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show what is in force.").set_defaults(func=cmd_status)
    sub.add_parser("detect", help="List browsers and their policy keys.").set_defaults(
        func=cmd_detect
    )
    sub.add_parser("apply", help="Write policy to every browser.").set_defaults(func=cmd_apply)
    sub.add_parser("verify", help="Read back what is actually live.").set_defaults(func=cmd_verify)
    sub.add_parser("categories", help="List bundled blocklist categories.").set_defaults(
        func=cmd_categories
    )

    level = sub.add_parser("level", help="Set the protection level.")
    level.add_argument("level", choices=[l for l in LEVELS if l != LEVEL_CUSTOM])
    level.add_argument("--passcode", help="Skip the waiting period.")
    level.set_defaults(func=cmd_level)

    for name, func, helptext in (
        ("block", cmd_block, "Block one or more sites."),
        ("unblock", cmd_unblock, "Stop blocking one or more sites."),
        ("allow", cmd_allow, "Allow sites through the blocklist."),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("domains", nargs="+")
        p.add_argument("--passcode", help="Skip the waiting period.")
        p.set_defaults(func=func)

    passcode = sub.add_parser("passcode", help="Generate a new passcode and save it to a file.")
    passcode.add_argument("--out", help="Where to write the passcode file.")
    passcode.set_defaults(func=cmd_passcode)

    cd = sub.add_parser("cooldown", help="Set the waiting period in hours.")
    cd.add_argument("hours", type=float)
    cd.add_argument("--passcode", help="Needed to shorten the period.")
    cd.set_defaults(func=cmd_cooldown)

    pending = sub.add_parser("pending", help="Show or cancel a pending change.")
    pending.add_argument("--cancel", action="store_true")
    pending.set_defaults(func=cmd_pending)

    background = sub.add_parser("background", help="Manage the scheduled sync task.")
    background.add_argument("action", choices=["status", "install", "remove"], nargs="?", default="status")
    background.add_argument("--interval", type=int, default=scheduler.DEFAULT_INTERVAL_MINUTES)
    background.set_defaults(func=cmd_background)

    uninstall = sub.add_parser("uninstall", help="Remove all policy written by BrowserGuard.")
    uninstall.add_argument("--passcode", help="Skip the waiting period.")
    uninstall.add_argument("--force", action="store_true", help="Skip the waiting period as admin.")
    uninstall.set_defaults(func=cmd_uninstall)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.sync:
        return cmd_sync(args)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except BrowserGuardError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
