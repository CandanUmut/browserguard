"""Turning protection settings into concrete browser policy.

Chromium and Firefox express the same ideas with different policy names and
value shapes, so each family gets its own plan builder. Everything written lives
under the browser's policy key in HKLM and is removed cleanly on uninstall.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from browserguard.core import blocklists
from browserguard.core.browsers import CHROMIUM, FIREFOX, DetectedBrowser
from browserguard.core.registry import REG_DWORD, REG_SZ, Registry

# Chromium refuses to load a URLBlocklist longer than this.
CHROMIUM_BLOCKLIST_LIMIT = 1000

# Policy value names BrowserGuard manages. Anything here is removed on uninstall,
# so an unmanaged value set by someone else is never touched.
CHROMIUM_MANAGED_VALUES = (
    "ForceGoogleSafeSearch",
    "ForceBingSafeSearch",
    "ForceYouTubeRestrict",
    "SafeSitesFilterBehavior",
    "IncognitoModeAvailability",
    "DeveloperToolsAvailability",
    "BrowserGuestModeEnabled",
    "DnsOverHttpsMode",
    "BuiltInDnsClientEnabled",
)
CHROMIUM_MANAGED_SUBKEYS = ("URLBlocklist", "URLAllowlist", "ExtensionInstallBlocklist")

FIREFOX_MANAGED_VALUES = (
    "DisablePrivateBrowsing",
    "DisableDeveloperTools",
    "BlockAboutConfig",
)
FIREFOX_MANAGED_SUBKEYS = ("WebsiteFilter", "DNSOverHTTPS")

YOUTUBE_MODES = {"off": 0, "moderate": 1, "strict": 2}


@dataclass(frozen=True)
class PolicyValue:
    """A single registry value to write under a browser's policy key."""

    name: str
    value: object
    kind: str


@dataclass(frozen=True)
class PolicyList:
    """A Chromium/Firefox list policy, stored as a numbered subkey."""

    subkey: str
    entries: tuple[str, ...]


@dataclass
class PolicyPlan:
    """Everything to write for one browser."""

    policy_key: str
    values: list[PolicyValue] = field(default_factory=list)
    lists: list[PolicyList] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def value_count(self) -> int:
        return len(self.values) + sum(len(pl.entries) for pl in self.lists)


def _blocked_patterns(settings) -> list[str]:
    patterns = blocklists.expand_categories(settings.blocked_categories)
    seen = set(patterns)
    for raw in settings.custom_blocked:
        pattern = blocklists.normalise_pattern(raw)
        if pattern and pattern not in seen:
            seen.add(pattern)
            patterns.append(pattern)
    return patterns


def _allowed_patterns(settings) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in settings.allowed:
        pattern = blocklists.normalise_pattern(raw)
        if pattern and pattern not in seen:
            seen.add(pattern)
            result.append(pattern)
    return result


def build_chromium_plan(settings, policy_key: str) -> PolicyPlan:
    """Build the policy plan for a Chromium-family browser."""
    plan = PolicyPlan(policy_key=policy_key)
    blocked = _blocked_patterns(settings)
    allowed = _allowed_patterns(settings)

    if settings.allowlist_only:
        # Block everything, then punch through with the allowlist.
        plan.lists.append(PolicyList("URLBlocklist", ("*",)))
        if not allowed:
            plan.warnings.append(
                "Allowlist-only mode is on but the allowlist is empty, so every "
                "site will be blocked."
            )
    else:
        if len(blocked) > CHROMIUM_BLOCKLIST_LIMIT:
            plan.warnings.append(
                f"{len(blocked)} blocked entries exceeds Chromium's "
                f"{CHROMIUM_BLOCKLIST_LIMIT}-entry limit; the list was truncated."
            )
            blocked = blocked[:CHROMIUM_BLOCKLIST_LIMIT]
        if blocked:
            plan.lists.append(PolicyList("URLBlocklist", tuple(blocked)))

    if allowed:
        plan.lists.append(PolicyList("URLAllowlist", tuple(allowed)))

    if settings.safe_search:
        plan.values.append(PolicyValue("ForceGoogleSafeSearch", 1, REG_DWORD))
        plan.values.append(PolicyValue("ForceBingSafeSearch", 1, REG_DWORD))

    youtube = YOUTUBE_MODES.get(settings.youtube_restrict, 0)
    if youtube:
        plan.values.append(PolicyValue("ForceYouTubeRestrict", youtube, REG_DWORD))
        plan.warnings.append(
            "YouTube Restricted Mode hides all comments and blocks most live "
            "streams. That is the expected behaviour, not a fault."
        )

    if settings.safe_sites:
        # Chrome-only, ignored elsewhere. Classifies pages server-side, so it
        # catches adult sites that are not on any blocklist.
        plan.values.append(PolicyValue("SafeSitesFilterBehavior", 1, REG_DWORD))

    if settings.block_incognito:
        plan.values.append(PolicyValue("IncognitoModeAvailability", 1, REG_DWORD))
    if settings.block_devtools:
        # Without this, F12 lets a user edit the page and inspect requests.
        plan.values.append(PolicyValue("DeveloperToolsAvailability", 2, REG_DWORD))
    if settings.block_guest_mode:
        plan.values.append(PolicyValue("BrowserGuestModeEnabled", 0, REG_DWORD))

    if settings.force_plain_dns:
        # Browser-level DoH bypasses any DNS filtering on the machine.
        plan.values.append(PolicyValue("DnsOverHttpsMode", "off", REG_SZ))
        plan.values.append(PolicyValue("BuiltInDnsClientEnabled", 0, REG_DWORD))

    if settings.lock_extensions:
        plan.lists.append(PolicyList("ExtensionInstallBlocklist", ("*",)))
        plan.warnings.append(
            "Extension lockdown blocks all new extension installs, including "
            "ones already wanted. Existing extensions keep working."
        )

    return plan


def _firefox_match_pattern(domain: str) -> str:
    """Firefox WebsiteFilter uses MDN match patterns rather than bare hosts."""
    return f"*://*.{domain}/*"


def build_firefox_plan(settings, policy_key: str) -> PolicyPlan:
    """Build the policy plan for a Firefox-family browser."""
    plan = PolicyPlan(policy_key=policy_key)
    blocked = _blocked_patterns(settings)
    allowed = _allowed_patterns(settings)

    if settings.allowlist_only:
        plan.lists.append(PolicyList("WebsiteFilter\\Block", ("<all_urls>",)))
    elif blocked:
        plan.lists.append(
            PolicyList(
                "WebsiteFilter\\Block",
                tuple(_firefox_match_pattern(d) for d in blocked),
            )
        )
    if allowed:
        plan.lists.append(
            PolicyList(
                "WebsiteFilter\\Exceptions",
                tuple(_firefox_match_pattern(d) for d in allowed),
            )
        )

    if settings.block_incognito:
        plan.values.append(PolicyValue("DisablePrivateBrowsing", 1, REG_DWORD))
    if settings.block_devtools:
        plan.values.append(PolicyValue("DisableDeveloperTools", 1, REG_DWORD))
    if settings.force_plain_dns:
        plan.values.append(PolicyValue("DNSOverHTTPS\\Enabled", 0, REG_DWORD))
        plan.values.append(PolicyValue("DNSOverHTTPS\\Locked", 1, REG_DWORD))
    # about:config can undo much of the above by hand.
    plan.values.append(PolicyValue("BlockAboutConfig", 1, REG_DWORD))

    if settings.safe_search:
        plan.warnings.append(
            "Firefox has no SafeSearch policy. Search filtering there relies on "
            "the DNS layer instead."
        )
    return plan


def build_plan(settings, browser: DetectedBrowser) -> PolicyPlan:
    """Build the right plan for whichever family this browser belongs to."""
    if browser.family == FIREFOX:
        return build_firefox_plan(settings, browser.policy_key)
    if browser.family == CHROMIUM:
        return build_chromium_plan(settings, browser.policy_key)
    raise ValueError(f"Unknown browser family: {browser.family}")


def apply_plan(registry: Registry, plan: PolicyPlan) -> None:
    """Write a plan to the registry, clearing anything stale first."""
    clear_policies(registry, plan.policy_key, family_subkeys=_subkeys_for(plan))

    for value in plan.values:
        if "\\" in value.name:
            subkey, name = value.name.rsplit("\\", 1)
            registry.set_value(f"{plan.policy_key}\\{subkey}", name, value.value, value.kind)
        else:
            registry.set_value(plan.policy_key, value.name, value.value, value.kind)

    for policy_list in plan.lists:
        target = f"{plan.policy_key}\\{policy_list.subkey}"
        for index, entry in enumerate(policy_list.entries, start=1):
            registry.set_value(target, str(index), entry, REG_SZ)


def _subkeys_for(plan: PolicyPlan) -> tuple[str, ...]:
    if "Mozilla" in plan.policy_key:
        return FIREFOX_MANAGED_SUBKEYS
    return CHROMIUM_MANAGED_SUBKEYS


def clear_policies(
    registry: Registry, policy_key: str, family_subkeys: tuple[str, ...] | None = None
) -> None:
    """Remove only the values BrowserGuard manages, leaving anything else alone."""
    is_firefox = "Mozilla" in policy_key
    values = FIREFOX_MANAGED_VALUES if is_firefox else CHROMIUM_MANAGED_VALUES
    subkeys = family_subkeys or (
        FIREFOX_MANAGED_SUBKEYS if is_firefox else CHROMIUM_MANAGED_SUBKEYS
    )
    for name in values:
        registry.delete_value(policy_key, name)
    for subkey in subkeys:
        registry.delete_tree(f"{policy_key}\\{subkey}")


def read_applied(registry: Registry, policy_key: str) -> dict[str, object]:
    """Read back what is actually live under a policy key, for verification."""
    is_firefox = "Mozilla" in policy_key
    result: dict[str, object] = {}
    for name, value in registry.list_values(policy_key).items():
        result[name] = value
    subkeys = FIREFOX_MANAGED_SUBKEYS if is_firefox else CHROMIUM_MANAGED_SUBKEYS
    for subkey in subkeys:
        entries = registry.list_values(f"{policy_key}\\{subkey}")
        if entries:
            ordered = [entries[k] for k in sorted(entries, key=lambda s: int(s) if s.isdigit() else 0)]
            result[subkey] = ordered
        # Firefox nests one level deeper (WebsiteFilter\Block).
        for nested in ("Block", "Exceptions", "Enabled", "Locked"):
            nested_entries = registry.list_values(f"{policy_key}\\{subkey}\\{nested}")
            if nested_entries:
                result[f"{subkey}\\{nested}"] = list(nested_entries.values())
    return result
