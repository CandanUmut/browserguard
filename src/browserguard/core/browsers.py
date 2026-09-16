"""Detecting installed browsers and working out which policy target each one reads.

Most parental-control tools hardcode Chrome, Edge and Firefox. Any other
Chromium fork then silently ignores every policy that is written, which turns
that browser into an unguarded hole. BrowserGuard also identifies unknown
Chromium installs from the browser's own files, so forks are caught rather than
missed:

* Windows - the policy registry path is a literal string inside ``chrome.dll``.
* macOS   - the policy domain is the bundle identifier in ``Info.plist``.
"""

from __future__ import annotations

import os
import plistlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

CHROMIUM = "chromium"
FIREFOX = "firefox"

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

# Policy paths that appear inside a Chromium binary but are not the browser's
# own policy root, and would be wrong to write to.
_IGNORED_POLICY_PREFIXES = (
    "SOFTWARE\\Policies\\Microsoft\\Windows",
    "SOFTWARE\\Policies\\Microsoft\\Cryptography",
    "SOFTWARE\\Policies\\Microsoft\\SystemCertificates",
    "SOFTWARE\\Policies\\Microsoft\\Internet Explorer",
)

_POLICY_RE = re.compile(rb"SOFTWARE\\Policies\\[A-Za-z0-9 _.\\-]{2,60}")

MAC_APPLICATIONS = (Path("/Applications"), Path.home() / "Applications")


@dataclass(frozen=True)
class BrowserDef:
    """A browser BrowserGuard knows how to manage."""

    id: str
    name: str
    family: str
    policy_key: str = ""
    mac_domain: str = ""
    exe_names: tuple[str, ...] = ()
    install_hints: tuple[str, ...] = ()
    mac_app_names: tuple[str, ...] = ()

    def target(self) -> str:
        """The policy target for the platform this is running on."""
        return self.mac_domain if IS_MACOS else self.policy_key


@dataclass
class DetectedBrowser:
    """A browser actually found on this machine."""

    definition: BrowserDef
    install_path: Path | None = None
    detected_via: str = "known"
    notes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def family(self) -> str:
        return self.definition.family

    @property
    def policy_key(self) -> str:
        return self.definition.target()

    @property
    def installed(self) -> bool:
        return self.detected_via not in {"preemptive", "always"}


KNOWN_BROWSERS: tuple[BrowserDef, ...] = (
    BrowserDef(
        id="chrome",
        name="Google Chrome",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\Google\\Chrome",
        mac_domain="com.google.Chrome",
        exe_names=("chrome.exe",),
        install_hints=("Google\\Chrome\\Application",),
        mac_app_names=("Google Chrome.app",),
    ),
    BrowserDef(
        id="edge",
        name="Microsoft Edge",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\Microsoft\\Edge",
        mac_domain="com.microsoft.Edge",
        exe_names=("msedge.exe",),
        install_hints=("Microsoft\\Edge\\Application",),
        mac_app_names=("Microsoft Edge.app",),
    ),
    BrowserDef(
        id="brave",
        name="Brave",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\BraveSoftware\\Brave",
        mac_domain="com.brave.Browser",
        exe_names=("brave.exe",),
        install_hints=("BraveSoftware\\Brave-Browser\\Application",),
        mac_app_names=("Brave Browser.app",),
    ),
    BrowserDef(
        id="vivaldi",
        name="Vivaldi",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\Vivaldi",
        mac_domain="com.vivaldi.Vivaldi",
        exe_names=("vivaldi.exe",),
        install_hints=("Vivaldi\\Application",),
        mac_app_names=("Vivaldi.app",),
    ),
    BrowserDef(
        id="opera",
        name="Opera",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\Opera Software\\Opera",
        mac_domain="com.operasoftware.Opera",
        exe_names=("opera.exe", "launcher.exe"),
        install_hints=("Opera", "Programs\\Opera"),
        mac_app_names=("Opera.app",),
    ),
    BrowserDef(
        id="firefox",
        name="Mozilla Firefox",
        family=FIREFOX,
        policy_key="SOFTWARE\\Policies\\Mozilla\\Firefox",
        mac_domain="org.mozilla.firefox",
        exe_names=("firefox.exe",),
        install_hints=("Mozilla Firefox",),
        mac_app_names=("Firefox.app",),
    ),
    BrowserDef(
        id="waterfox",
        name="Waterfox",
        family=FIREFOX,
        policy_key="SOFTWARE\\Policies\\Mozilla\\Firefox",
        mac_domain="org.mozilla.firefox",
        exe_names=("waterfox.exe",),
        install_hints=("Waterfox",),
        mac_app_names=("Waterfox.app",),
    ),
)

# Every unbranded Chromium fork reads this target. Ecosia is the case that
# prompted it: it ships as plain Chromium and ignores vendor-specific roots.
GENERIC_CHROMIUM = BrowserDef(
    id="chromium",
    name="Chromium & unbranded forks",
    family=CHROMIUM,
    policy_key="SOFTWARE\\Policies\\Chromium",
    mac_domain="org.chromium.Chromium",
    exe_names=("chrome.exe", "chromium.exe"),
    mac_app_names=("Chromium.app",),
)

_SEARCH_ROOT_VARS = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA")


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


def _search_roots() -> list[Path]:
    roots: list[Path] = []
    for name in _SEARCH_ROOT_VARS:
        value = os.environ.get(name)
        if not value:
            continue
        path = Path(value)
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def _find_install_windows(defn: BrowserDef) -> Path | None:
    for root in _search_roots():
        for hint in defn.install_hints:
            candidate = root / hint
            if not candidate.is_dir():
                continue
            for exe in defn.exe_names:
                if (candidate / exe).exists():
                    return candidate
            for exe in defn.exe_names:
                if any(candidate.glob("*/" + exe)):
                    return candidate
    return None


def extract_policy_key(binary: Path, limit_bytes: int = 400 * 1024 * 1024) -> str | None:
    """Read the policy root a Chromium binary actually uses (Windows).

    Chromium stores its policy registry path as a literal string in the binary.
    Reading it is far more reliable than guessing a vendor name. Both ASCII and
    UTF-16LE encodings are searched, since Chromium uses each in different places.
    """
    try:
        if binary.stat().st_size > limit_bytes:
            return None
        blob = binary.read_bytes()
    except OSError:
        return None

    candidates: list[str] = []
    for match in _POLICY_RE.finditer(blob):
        candidates.append(match.group().decode("ascii", "ignore"))
    # UTF-16LE: drop the interleaved null bytes, then run the same search. Both
    # byte alignments are tried, since a wide string can start at an odd offset.
    for offset in (0, 1):
        for match in _POLICY_RE.finditer(blob[offset::2]):
            candidates.append(match.group().decode("ascii", "ignore"))

    best: str | None = None
    for raw in candidates:
        cleaned = raw.rstrip("\\ ")
        if cleaned.startswith(_IGNORED_POLICY_PREFIXES):
            continue
        depth = cleaned.count("\\")
        if depth < 2:
            continue
        if best is None or depth < best.count("\\"):
            best = cleaned
    return best


def _chromium_binary(install_path: Path) -> Path | None:
    direct = install_path / "chrome.dll"
    if direct.exists():
        return direct
    versioned = sorted(install_path.glob("*/chrome.dll"), reverse=True)
    if versioned:
        return versioned[0]
    for exe in ("chrome.exe", "chromium.exe"):
        candidate = install_path / exe
        if candidate.exists():
            return candidate
    return None


def _scan_unknown_windows(deep_scan: bool) -> list[DetectedBrowser]:
    known_top_dirs = {
        hint.split("\\")[0].lower()
        for defn in KNOWN_BROWSERS
        for hint in defn.install_hints
    }
    found: list[DetectedBrowser] = []
    seen: set[str] = set()

    for root in _search_roots():
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name.lower() in known_top_dirs:
                continue
            for app_dir in (entry / "Application", entry):
                if not app_dir.is_dir():
                    continue
                binary = _chromium_binary(app_dir)
                if binary is None:
                    continue
                policy_key = extract_policy_key(binary) if deep_scan else None
                if policy_key is None:
                    policy_key = GENERIC_CHROMIUM.policy_key
                    via, note = "assumed-chromium", "Chromium fork; assumed the generic policy key"
                else:
                    via, note = "binary-scan", f"Policy key read from {binary.name}"
                if policy_key in seen:
                    break
                seen.add(policy_key)
                found.append(
                    DetectedBrowser(
                        definition=BrowserDef(
                            id="fork:" + entry.name.lower(),
                            name=entry.name,
                            family=CHROMIUM,
                            policy_key=policy_key,
                            exe_names=GENERIC_CHROMIUM.exe_names,
                        ),
                        install_path=app_dir,
                        detected_via=via,
                        notes=[note],
                    )
                )
                break
    return found


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------


def bundle_identifier(app: Path) -> str | None:
    """Read ``CFBundleIdentifier`` from an application bundle.

    On macOS this is the policy domain, so it is the direct equivalent of the
    registry path scan done on Windows - and rather more pleasant to obtain.
    """
    info = app / "Contents" / "Info.plist"
    try:
        with info.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return None
    value = data.get("CFBundleIdentifier")
    return value if isinstance(value, str) and value else None


def _is_chromium_bundle(app: Path) -> bool:
    frameworks = app / "Contents" / "Frameworks"
    if not frameworks.is_dir():
        return False
    return any(f.name.endswith("Framework.framework") for f in frameworks.iterdir())


def _find_install_macos(defn: BrowserDef) -> Path | None:
    for root in MAC_APPLICATIONS:
        for name in defn.mac_app_names:
            candidate = root / name
            if candidate.is_dir():
                return candidate
    return None


def _scan_unknown_macos() -> list[DetectedBrowser]:
    known = {name.lower() for defn in KNOWN_BROWSERS for name in defn.mac_app_names}
    known.update(n.lower() for n in GENERIC_CHROMIUM.mac_app_names)
    found: list[DetectedBrowser] = []
    seen: set[str] = set()

    for root in MAC_APPLICATIONS:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for app in entries:
            if app.suffix != ".app" or app.name.lower() in known:
                continue
            if not _is_chromium_bundle(app):
                continue
            domain = bundle_identifier(app)
            if not domain or domain in seen:
                continue
            seen.add(domain)
            found.append(
                DetectedBrowser(
                    definition=BrowserDef(
                        id="fork:" + app.stem.lower(),
                        name=app.stem,
                        family=CHROMIUM,
                        mac_domain=domain,
                    ),
                    install_path=app,
                    detected_via="bundle-scan",
                    notes=[f"Policy domain read from Info.plist: {domain}"],
                )
            )
    return found


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def scan_unknown_chromium(deep_scan: bool = True) -> list[DetectedBrowser]:
    """Find Chromium-based browsers that are not in :data:`KNOWN_BROWSERS`."""
    if IS_MACOS:
        return _scan_unknown_macos()
    if IS_WINDOWS:
        return _scan_unknown_windows(deep_scan)
    return []


def detect_browsers(deep_scan: bool = True) -> list[DetectedBrowser]:
    """Return every browser found on this machine.

    The generic Chromium target is always included even when no fork is
    detected: writing it is harmless, and it covers a fork installed later.
    """
    find_install = _find_install_macos if IS_MACOS else _find_install_windows

    detected: list[DetectedBrowser] = []
    for defn in KNOWN_BROWSERS:
        install = find_install(defn)
        if install is not None:
            detected.append(DetectedBrowser(definition=defn, install_path=install))

    detected.append(
        DetectedBrowser(
            definition=GENERIC_CHROMIUM,
            detected_via="always",
            notes=["Covers Ecosia and other unbranded Chromium forks"],
        )
    )

    # Forks are kept even when they share a target with the generic Chromium
    # entry, so the user can see that their browser was actually recognised.
    # De-duplication by target happens at write time, not here.
    known_targets = {d.policy_key for d in detected}
    for fork in scan_unknown_chromium(deep_scan=deep_scan):
        if fork.policy_key in known_targets:
            fork.notes.append("Covered by the entry above; nothing extra to write")
        detected.append(fork)
    return detected


def all_policy_targets(deep_scan: bool = True) -> list[DetectedBrowser]:
    """One entry per distinct policy target that should be written.

    Writing policy for a browser that is not installed costs nothing and means
    protection is already in force if that browser is installed later. Several
    browsers can share a target (every unbranded Chromium fork does), so this
    collapses them to avoid writing the same one twice.
    """
    targets: list[DetectedBrowser] = []
    seen: set[str] = set()
    for browser in detect_browsers(deep_scan=deep_scan):
        if browser.policy_key and browser.policy_key not in seen:
            targets.append(browser)
            seen.add(browser.policy_key)
    for defn in KNOWN_BROWSERS:
        target = defn.target()
        if target and target not in seen:
            targets.append(
                DetectedBrowser(
                    definition=defn,
                    detected_via="preemptive",
                    notes=["Not installed; covered if it is installed later"],
                )
            )
            seen.add(target)
    return targets
