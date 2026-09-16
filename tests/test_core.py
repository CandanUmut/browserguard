"""Tests for the BrowserGuard core.

These run on any platform: the registry is swapped for an in-memory stand-in, so
nothing here touches a real machine.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from browserguard.core import blocklists, cooldown, policies, schedules
from browserguard.core.browsers import (
    CHROMIUM,
    FIREFOX,
    BrowserDef,
    DetectedBrowser,
    extract_policy_key,
)
from browserguard.core.config import (
    LEVEL_LIGHT,
    LEVEL_OFF,
    LEVEL_STRICT,
    AppConfig,
    ProtectionSettings,
    preset,
    strictness_score,
)
from browserguard.core.passcode import (
    generate_passcode,
    hash_passcode,
    normalise,
    verify_passcode,
)
from browserguard.core.registry import MemoryRegistry

CHROME = DetectedBrowser(
    definition=BrowserDef(
        id="chrome",
        name="Chrome",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\Google\\Chrome",
    )
)
FIREFOX_BROWSER = DetectedBrowser(
    definition=BrowserDef(
        id="firefox",
        name="Firefox",
        family=FIREFOX,
        policy_key="SOFTWARE\\Policies\\Mozilla\\Firefox",
    )
)


# --------------------------------------------------------------------------
# Blocklists
# --------------------------------------------------------------------------


def test_bundled_categories_load():
    for category in blocklists.CATEGORIES:
        entries = blocklists.load_category(category.id)
        assert entries, f"category {category.id} is empty"
        assert all(not e.startswith("#") for e in entries)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://www.Example.com/path?x=1", "example.com"),
        ("http://example.com", "example.com"),
        ("  Example.COM  ", "example.com"),
        ("www.sub.example.com", "sub.example.com"),
        ("", ""),
    ],
)
def test_normalise_pattern(raw, expected):
    assert blocklists.normalise_pattern(raw) == expected


def test_expand_categories_deduplicates():
    # onlyfans.com appears in both adult and social.
    merged = blocklists.expand_categories(["adult", "social"])
    assert len(merged) == len(set(merged))


# --------------------------------------------------------------------------
# Policy building
# --------------------------------------------------------------------------


def test_chromium_plan_writes_blocklist():
    settings = preset(LEVEL_LIGHT)
    plan = policies.build_chromium_plan(settings, CHROME.policy_key)
    lists = {pl.subkey: pl.entries for pl in plan.lists}
    assert "URLBlocklist" in lists
    assert "pornhub.com" in lists["URLBlocklist"]
    names = {v.name for v in plan.values}
    assert "ForceGoogleSafeSearch" in names
    assert "DnsOverHttpsMode" in names


def test_youtube_restrict_off_by_default_and_warns_when_on():
    settings = preset(LEVEL_LIGHT)
    assert settings.youtube_restrict == "off"
    plan = policies.build_chromium_plan(settings, CHROME.policy_key)
    assert "ForceYouTubeRestrict" not in {v.name for v in plan.values}

    settings.youtube_restrict = "strict"
    plan = policies.build_chromium_plan(settings, CHROME.policy_key)
    value = next(v for v in plan.values if v.name == "ForceYouTubeRestrict")
    assert value.value == 2
    assert any("comments" in w for w in plan.warnings)


def test_allowlist_only_blocks_everything():
    settings = preset(LEVEL_STRICT)
    settings.allowlist_only = True
    settings.allowed = ["wikipedia.org"]
    plan = policies.build_chromium_plan(settings, CHROME.policy_key)
    lists = {pl.subkey: pl.entries for pl in plan.lists}
    assert lists["URLBlocklist"] == ("*",)
    assert lists["URLAllowlist"] == ("wikipedia.org",)


def test_allowlist_only_with_empty_allowlist_warns():
    settings = preset(LEVEL_STRICT)
    settings.allowlist_only = True
    settings.allowed = []
    plan = policies.build_chromium_plan(settings, CHROME.policy_key)
    assert any("every site will be blocked" in w for w in plan.warnings)


def test_blocklist_truncated_at_chromium_limit():
    settings = preset(LEVEL_LIGHT)
    settings.custom_blocked = [f"example{i}.com" for i in range(1200)]
    plan = policies.build_chromium_plan(settings, CHROME.policy_key)
    entries = next(pl for pl in plan.lists if pl.subkey == "URLBlocklist").entries
    assert len(entries) == policies.CHROMIUM_BLOCKLIST_LIMIT
    assert any("limit" in w for w in plan.warnings)


def test_firefox_uses_match_patterns():
    settings = preset(LEVEL_LIGHT)
    plan = policies.build_firefox_plan(settings, FIREFOX_BROWSER.policy_key)
    block = next(pl for pl in plan.lists if pl.subkey.endswith("Block")).entries
    assert all(p.startswith("*://*.") and p.endswith("/*") for p in block)


def test_apply_and_clear_roundtrip():
    registry = MemoryRegistry()
    settings = preset(LEVEL_LIGHT)
    plan = policies.build_chromium_plan(settings, CHROME.policy_key)
    policies.apply_plan(registry, plan)

    applied = policies.read_applied(registry, CHROME.policy_key)
    assert applied["ForceGoogleSafeSearch"] == 1
    assert "pornhub.com" in applied["URLBlocklist"]

    policies.clear_policies(registry, CHROME.policy_key)
    applied = policies.read_applied(registry, CHROME.policy_key)
    assert "ForceGoogleSafeSearch" not in applied
    assert "URLBlocklist" not in applied


def test_apply_replaces_stale_entries():
    """A shorter blocklist must not leave old numbered entries behind."""
    registry = MemoryRegistry()
    settings = preset(LEVEL_STRICT)
    policies.apply_plan(registry, policies.build_chromium_plan(settings, CHROME.policy_key))
    first = len(policies.read_applied(registry, CHROME.policy_key)["URLBlocklist"])

    smaller = preset(LEVEL_LIGHT)
    policies.apply_plan(registry, policies.build_chromium_plan(smaller, CHROME.policy_key))
    second = len(policies.read_applied(registry, CHROME.policy_key)["URLBlocklist"])
    assert second < first


def test_clear_leaves_unmanaged_values_alone():
    registry = MemoryRegistry()
    registry.set_value(CHROME.policy_key, "HomepageLocation", "https://example.com", "sz")
    policies.apply_plan(
        registry, policies.build_chromium_plan(preset(LEVEL_LIGHT), CHROME.policy_key)
    )
    policies.clear_policies(registry, CHROME.policy_key)
    assert registry.get_value(CHROME.policy_key, "HomepageLocation") == "https://example.com"


# --------------------------------------------------------------------------
# Passcode
# --------------------------------------------------------------------------


def test_passcode_roundtrip():
    code = generate_passcode()
    digest, salt = hash_passcode(code)
    assert verify_passcode(code, digest, salt)
    assert not verify_passcode("WRONG-CODE-HERE", digest, salt)


def test_passcode_accepts_loose_formatting():
    code = generate_passcode()
    digest, salt = hash_passcode(code)
    assert verify_passcode(code.lower().replace("-", " "), digest, salt)


def test_passcode_avoids_ambiguous_characters():
    for _ in range(50):
        assert not set(normalise(generate_passcode())) & set("O01IL5S8B")


def test_verify_rejects_empty():
    digest, salt = hash_passcode("ABCD-EFGH-JKMN-PQRT")
    assert not verify_passcode("", digest, salt)


# --------------------------------------------------------------------------
# Cooldown - the security model
# --------------------------------------------------------------------------


def _config(hours: float = 24.0) -> AppConfig:
    config = AppConfig()
    config.security.cooldown_hours = hours
    config.protection = preset(LEVEL_LIGHT)
    return config


def test_tightening_applies_immediately():
    config = _config()
    updated, result = cooldown.request_change(config, preset(LEVEL_STRICT))
    assert result.applied
    assert updated.pending is None
    assert updated.protection.level == LEVEL_STRICT


def test_loosening_is_delayed():
    config = _config()
    config.protection = preset(LEVEL_STRICT)
    updated, result = cooldown.request_change(config, preset(LEVEL_LIGHT))
    assert not result.applied
    assert updated.pending is not None
    # Protection stays strict until the wait elapses.
    assert updated.protection.level == LEVEL_STRICT


def test_passcode_skips_the_wait():
    config = _config()
    config.protection = preset(LEVEL_STRICT)
    updated, result = cooldown.request_change(config, preset(LEVEL_OFF), passcode_ok=True)
    assert result.applied
    assert updated.pending is None
    assert updated.protection.enabled is False


def test_pending_change_applies_once_due():
    """The heart of the design: waiting alone is always enough."""
    now = datetime.now(timezone.utc)
    config = _config(hours=24)
    config.protection = preset(LEVEL_STRICT)
    config, _ = cooldown.request_change(config, preset(LEVEL_OFF), now=now)
    assert config.pending is not None

    # Too early.
    config_early, promoted = cooldown.promote_due_change(config, now + timedelta(hours=23))
    assert not promoted
    assert config_early.protection.level == LEVEL_STRICT

    # After the wait, it lands with no passcode involved.
    config_late, promoted = cooldown.promote_due_change(config, now + timedelta(hours=25))
    assert promoted
    assert config_late.protection.enabled is False
    assert config_late.pending is None


def test_zero_cooldown_applies_immediately():
    config = _config(hours=0)
    config.protection = preset(LEVEL_STRICT)
    _, result = cooldown.request_change(config, preset(LEVEL_OFF))
    assert result.applied


def test_cancelling_pending_is_always_allowed():
    config = _config()
    config.protection = preset(LEVEL_STRICT)
    config, _ = cooldown.request_change(config, preset(LEVEL_OFF))
    assert config.pending is not None
    config, result = cooldown.cancel_pending(config)
    assert config.pending is None
    assert "cancelled" in result.message


def test_strictness_ordering():
    assert strictness_score(preset(LEVEL_OFF)) < strictness_score(preset(LEVEL_LIGHT))
    assert strictness_score(preset(LEVEL_LIGHT)) < strictness_score(preset(LEVEL_STRICT))


def test_adding_an_allowed_site_counts_as_loosening():
    current = preset(LEVEL_STRICT)
    proposed = preset(LEVEL_STRICT)
    proposed.allowed = ["pornhub.com"]
    assert cooldown.is_loosening(current, proposed)


def test_describe_change_mentions_unblocked_category():
    current = preset(LEVEL_STRICT)
    proposed = preset(LEVEL_STRICT)
    proposed.blocked_categories = [c for c in proposed.blocked_categories if c != "adult"]
    assert "adult" in cooldown.describe_change(current, proposed)


# --------------------------------------------------------------------------
# Schedules
# --------------------------------------------------------------------------


def test_schedule_active_within_window():
    schedule = schedules.Schedule(days=[0], start="09:00", end="15:00", categories=["social"])
    monday_10am = datetime(2026, 9, 14, 10, 0)  # a Monday
    monday_4pm = datetime(2026, 9, 14, 16, 0)
    assert schedules.is_active(schedule, monday_10am)
    assert not schedules.is_active(schedule, monday_4pm)


def test_overnight_schedule_wraps_midnight():
    schedule = schedules.Schedule(days=[0], start="22:00", end="06:00")
    monday_11pm = datetime(2026, 9, 14, 23, 0)
    tuesday_2am = datetime(2026, 9, 15, 2, 0)
    tuesday_9am = datetime(2026, 9, 15, 9, 0)
    assert schedules.is_active(schedule, monday_11pm)
    assert schedules.is_active(schedule, tuesday_2am)
    assert not schedules.is_active(schedule, tuesday_9am)


def test_disabled_schedule_never_active():
    schedule = schedules.Schedule(days=list(range(7)), start="00:00", end="23:59", enabled=False)
    assert not schedules.is_active(schedule, datetime(2026, 9, 14, 12, 0))


def test_schedule_adds_but_never_removes_restrictions():
    base = preset(LEVEL_LIGHT)
    schedule = schedules.Schedule(days=[0], start="09:00", end="15:00", categories=["social"])
    merged = schedules.effective_settings(base, [schedule], datetime(2026, 9, 14, 10, 0))
    assert "social" in merged.blocked_categories
    # Everything the base blocked is still blocked.
    assert set(base.blocked_categories) <= set(merged.blocked_categories)


def test_inactive_schedule_leaves_settings_untouched():
    base = preset(LEVEL_LIGHT)
    schedule = schedules.Schedule(days=[0], start="09:00", end="15:00", categories=["social"])
    merged = schedules.effective_settings(base, [schedule], datetime(2026, 9, 14, 20, 0))
    assert merged.blocked_categories == base.blocked_categories


# --------------------------------------------------------------------------
# Binary policy-key extraction
# --------------------------------------------------------------------------


def test_extract_policy_key_reads_ascii(tmp_path):
    binary = tmp_path / "chrome.dll"
    binary.write_bytes(b"junk\x00SOFTWARE\\Policies\\Chromium\x00more junk")
    assert extract_policy_key(binary) == "SOFTWARE\\Policies\\Chromium"


def test_extract_policy_key_reads_utf16(tmp_path):
    binary = tmp_path / "chrome.dll"
    binary.write_bytes(b"\x00" + "SOFTWARE\\Policies\\Vivaldi".encode("utf-16-le"))
    assert extract_policy_key(binary) == "SOFTWARE\\Policies\\Vivaldi"


def test_extract_policy_key_ignores_windows_policies(tmp_path):
    binary = tmp_path / "chrome.dll"
    binary.write_bytes(
        b"SOFTWARE\\Policies\\Microsoft\\Windows\\Safer\x00"
        b"SOFTWARE\\Policies\\BraveSoftware\\Brave\x00"
    )
    assert extract_policy_key(binary) == "SOFTWARE\\Policies\\BraveSoftware\\Brave"


def test_extract_policy_key_missing_file(tmp_path):
    assert extract_policy_key(tmp_path / "nope.dll") is None


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def test_config_roundtrip():
    config = AppConfig()
    config.protection = preset(LEVEL_STRICT)
    config.security.cooldown_hours = 48
    restored = AppConfig.from_dict(config.to_dict())
    assert restored.protection.level == LEVEL_STRICT
    assert restored.security.cooldown_hours == 48


def test_settings_from_dict_ignores_unknown_keys():
    settings = ProtectionSettings.from_dict({"level": "strict", "bogus_key": 1})
    assert settings.level == "strict"
