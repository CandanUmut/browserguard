"""Tests for the macOS policy backend and bundle detection.

These run on any platform: ``PlistRegistry`` is pointed at a temporary directory
rather than ``/Library/Managed Preferences``.
"""

from __future__ import annotations

import plistlib

import pytest

from browserguard.core import policies
from browserguard.core.browsers import (
    CHROMIUM,
    FIREFOX,
    KNOWN_BROWSERS,
    BrowserDef,
    DetectedBrowser,
    bundle_identifier,
)
from browserguard.core.config import LEVEL_LIGHT, LEVEL_STRICT, preset
from browserguard.core.macpolicy import PlistRegistry
from browserguard.core.registry import REG_BOOL, REG_DWORD, REG_SZ

CHROME_DOMAIN = "com.google.Chrome"


@pytest.fixture()
def store(tmp_path):
    return PlistRegistry(root=tmp_path)


def _read(tmp_path, domain=CHROME_DOMAIN):
    with (tmp_path / f"{domain}.plist").open("rb") as handle:
        return plistlib.load(handle)


# ---------------------------------------------------------------------------
# Value storage
# ---------------------------------------------------------------------------


def test_scalar_roundtrip(store, tmp_path):
    store.set_value(CHROME_DOMAIN, "DnsOverHttpsMode", "off", REG_SZ)
    assert store.get_value(CHROME_DOMAIN, "DnsOverHttpsMode") == "off"
    assert _read(tmp_path)["DnsOverHttpsMode"] == "off"


def test_booleans_are_real_plist_booleans(store, tmp_path):
    """A Chromium boolean policy is ignored on macOS if it arrives as an integer."""
    store.set_value(CHROME_DOMAIN, "ForceGoogleSafeSearch", True, REG_BOOL)
    value = _read(tmp_path)["ForceGoogleSafeSearch"]
    assert value is True
    assert isinstance(value, bool)


def test_integers_stay_integers(store, tmp_path):
    store.set_value(CHROME_DOMAIN, "IncognitoModeAvailability", 1, REG_DWORD)
    value = _read(tmp_path)["IncognitoModeAvailability"]
    assert value == 1
    assert isinstance(value, int) and not isinstance(value, bool)


def test_numbered_subkey_becomes_an_array(store, tmp_path):
    store.set_value(f"{CHROME_DOMAIN}\\URLBlocklist", "1", "a.com", REG_SZ)
    store.set_value(f"{CHROME_DOMAIN}\\URLBlocklist", "2", "b.com", REG_SZ)
    assert _read(tmp_path)["URLBlocklist"] == ["a.com", "b.com"]


def test_array_order_follows_numeric_not_lexical_order(store, tmp_path):
    for index in range(1, 12):
        store.set_value(f"{CHROME_DOMAIN}\\URLBlocklist", str(index), f"s{index}.com", REG_SZ)
    entries = _read(tmp_path)["URLBlocklist"]
    # Lexical ordering would put "10" before "2".
    assert entries[:3] == ["s1.com", "s2.com", "s3.com"]
    assert entries[-1] == "s11.com"


def test_nested_path_for_firefox(store, tmp_path):
    domain = "org.mozilla.firefox"
    store.set_value(f"{domain}\\WebsiteFilter\\Block", "1", "*://*.x.com/*", REG_SZ)
    store.set_value(f"{domain}\\DNSOverHTTPS", "Enabled", False, REG_BOOL)
    data = _read(tmp_path, domain)
    assert data["WebsiteFilter"]["Block"] == ["*://*.x.com/*"]
    assert data["DNSOverHTTPS"]["Enabled"] is False


def test_delete_value_and_tree(store):
    store.set_value(CHROME_DOMAIN, "ForceGoogleSafeSearch", True, REG_BOOL)
    store.set_value(f"{CHROME_DOMAIN}\\URLBlocklist", "1", "a.com", REG_SZ)
    store.delete_value(CHROME_DOMAIN, "ForceGoogleSafeSearch")
    assert store.get_value(CHROME_DOMAIN, "ForceGoogleSafeSearch") is None
    store.delete_tree(f"{CHROME_DOMAIN}\\URLBlocklist")
    assert store.list_values(f"{CHROME_DOMAIN}\\URLBlocklist") == {}


def test_list_values_skips_containers(store):
    store.set_value(CHROME_DOMAIN, "DnsOverHttpsMode", "off", REG_SZ)
    store.set_value(f"{CHROME_DOMAIN}\\URLBlocklist", "1", "a.com", REG_SZ)
    values = store.list_values(CHROME_DOMAIN)
    assert values == {"DnsOverHttpsMode": "off"}


def test_missing_domain_reads_empty(store):
    assert store.get_value("com.nope.Missing", "Anything") is None
    assert store.list_values("com.nope.Missing") == {}
    assert store.key_exists("com.nope.Missing") is False


# ---------------------------------------------------------------------------
# Applying a real plan through the macOS backend
# ---------------------------------------------------------------------------


def test_full_plan_applies_to_plist(store, tmp_path):
    browser = DetectedBrowser(
        definition=BrowserDef(
            id="chrome", name="Chrome", family=CHROMIUM, mac_domain=CHROME_DOMAIN
        )
    )
    plan = policies.build_chromium_plan(preset(LEVEL_LIGHT), CHROME_DOMAIN)
    policies.apply_plan(store, plan)

    data = _read(tmp_path)
    assert data["ForceGoogleSafeSearch"] is True
    assert "pornhub.com" in data["URLBlocklist"]
    assert data["DnsOverHttpsMode"] == "off"
    assert browser.family == CHROMIUM


def test_reapplying_a_smaller_list_shrinks_the_array(store, tmp_path):
    policies.apply_plan(store, policies.build_chromium_plan(preset(LEVEL_STRICT), CHROME_DOMAIN))
    first = len(_read(tmp_path)["URLBlocklist"])
    policies.apply_plan(store, policies.build_chromium_plan(preset(LEVEL_LIGHT), CHROME_DOMAIN))
    second = len(_read(tmp_path)["URLBlocklist"])
    assert second < first


def test_clear_uses_family_not_key_spelling(store):
    """The macOS Firefox domain has no backslashes, so family must be explicit."""
    domain = "org.mozilla.firefox"
    plan = policies.build_firefox_plan(preset(LEVEL_LIGHT), domain)
    assert plan.family == FIREFOX
    policies.apply_plan(store, plan)
    assert store.key_exists(f"{domain}\\WebsiteFilter")
    policies.clear_policies(store, domain, FIREFOX)
    assert store.list_values(f"{domain}\\WebsiteFilter\\Block") == {}


# ---------------------------------------------------------------------------
# Bundle identification
# ---------------------------------------------------------------------------


def test_bundle_identifier_read_from_info_plist(tmp_path):
    app = tmp_path / "Ecosia.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": "com.ecosia.browser"}, handle)
    assert bundle_identifier(app) == "com.ecosia.browser"


def test_bundle_identifier_missing(tmp_path):
    app = tmp_path / "Broken.app"
    (app / "Contents").mkdir(parents=True)
    assert bundle_identifier(app) is None


def test_every_known_browser_has_a_mac_domain():
    for defn in KNOWN_BROWSERS:
        assert defn.mac_domain, f"{defn.id} has no macOS policy domain"
        assert defn.mac_app_names, f"{defn.id} has no macOS app name"
