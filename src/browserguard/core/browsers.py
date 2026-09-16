"""Detecting installed browsers and working out which policy key each one reads.

Most parental-control tools hardcode Chrome, Edge and Firefox. Any other
Chromium fork then silently ignores every policy that is written, which turns
that browser into an unguarded hole. BrowserGuard also scans unknown Chromium
installs for the policy path baked into their binaries, so forks are caught
rather than missed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

CHROMIUM = "chromium"
FIREFOX = "firefox"

# Policy paths that appear inside a Chromium binary but are not the browser's
# own policy root, and would be wrong to write to.
_IGNORED_POLICY_PREFIXES = (
    r"SOFTWARE\Policies\Microsoft\Windows",
    r"SOFTWARE\Policies\Microsoft\Cryptography",
    r"SOFTWARE\Policies\Microsoft\SystemCertificates",
    r"SOFTWARE\Policies\Microsoft\Internet Explorer",
)

_POLICY_RE = re.compile(rb"SOFTWARE\\Policies\\[A-Za-z0-9 _.\\-]{2,60}")


@dataclass(frozen=True)
class BrowserDef:
    """A browser BrowserGuard knows how to manage."""

    id: str
    name: str
    family: str
    policy_key: str
    exe_names: tuple[str, ...] = ()
    install_hints: tuple[str, ...] = ()


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
        return self.definition.policy_key

    @property
    def installed(self) -> bool:
        return self.detected_via not in {"preemptive", "always"}


# Browsers with a documented, vendor-specific policy root.
KNOWN_BROWSERS: tuple[BrowserDef, ...] = (
    BrowserDef(
        id="chrome",
        name="Google Chrome",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\Google\\Chrome",
        exe_names=("chrome.exe",),
        install_hints=("Google\\Chrome\\Application",),
    ),
    BrowserDef(
        id="edge",
        name="Microsoft Edge",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\Microsoft\\Edge",
        exe_names=("msedge.exe",),
        install_hints=("Microsoft\\Edge\\Application",),
    ),
    BrowserDef(
        id="brave",
        name="Brave",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\BraveSoftware\\Brave",
        exe_names=("brave.exe",),
        install_hints=("BraveSoftware\\Brave-Browser\\Application",),
    ),
    BrowserDef(
        id="vivaldi",
        name="Vivaldi",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\Vivaldi",
        exe_names=("vivaldi.exe",),
        install_hints=("Vivaldi\\Application",),
    ),
    BrowserDef(
        id="opera",
        name="Opera",
        family=CHROMIUM,
        policy_key="SOFTWARE\\Policies\\Opera Software\\Opera",
        exe_names=("opera.exe", "launcher.exe"),
        install_hints=("Opera", "Programs\\Opera"),
    ),
    BrowserDef(
        id="firefox",
        name="Mozilla Firefox",
        family=FIREFOX,
        policy_key="SOFTWARE\\Policies\\Mozilla\\Firefox",
        exe_names=("firefox.exe",),
        install_hints=("Mozilla Firefox",),
    ),
    BrowserDef(
        id="waterfox",
        name="Waterfox",
        family=FIREFOX,
        policy_key="SOFTWARE\\Policies\\Mozilla\\Firefox",
        exe_names=("waterfox.exe",),
        install_hints=("Waterfox",),
    ),
)

# Every unbranded Chromium fork reads this key. Ecosia is the case that prompted
# it: it ships as plain Chromium and ignores all vendor-specific policy roots.
GENERIC_CHROMIUM = BrowserDef(
    id="chromium",
    name="Chromium & unbranded forks",
    family=CHROMIUM,
    policy_key="SOFTWARE\\Policies\\Chromium",
    exe_names=("chrome.exe", "chromium.exe"),
)

_SEARCH_ROOT_VARS = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA")


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


def _find_install(defn: BrowserDef) -> Path | None:
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
    """Read the policy root a Chromium binary actually uses.

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
        # Prefer the shallowest plausible root (Vendor or Vendor\Product).
        if best is None or depth < best.count("\\"):
            best = cleaned
    return best


def _chromium_binary(install_path: Path) -> Path | None:
    """Locate the binary that carries the policy string for a Chromium install."""
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


def scan_unknown_chromium(deep_scan: bool = True) -> list[DetectedBrowser]:
    """Find Chromium-based browsers that are not in :data:`KNOWN_BROWSERS`."""
    known_top_dirs = {
        hint.split("\\")[0].lower()
        for defn in KNOWN_BROWSERS
        for hint in defn.install_hints
    }
    found: list[DetectedBrowser] = []
    seen_keys: set[str] = set()

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
                    via = "assumed-chromium"
                    note = "Chromium fork; assumed the generic Chromium policy key"
                else:
                    via = "binary-scan"
                    note = "Policy key read from " + binary.name
                if policy_key in seen_keys:
                    break
                seen_keys.add(policy_key)
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


def detect_browsers(deep_scan: bool = True) -> list[DetectedBrowser]:
    """Return every browser found on this machine.

    The generic Chromium key is always included even when no fork is detected:
    writing it is harmless, and it covers a fork installed later.
    """
    detected: list[DetectedBrowser] = []
    for defn in KNOWN_BROWSERS:
        install = _find_install(defn)
        if install is not None:
            detected.append(DetectedBrowser(definition=defn, install_path=install))

    detected.append(
        DetectedBrowser(
            definition=GENERIC_CHROMIUM,
            detected_via="always",
            notes=["Covers Ecosia and other unbranded Chromium forks"],
        )
    )

    # Forks are kept even when they share a policy key with the generic Chromium
    # entry, so the user can see that their browser was actually recognised.
    # De-duplication by key happens at write time, not here.
    known_keys = {d.policy_key for d in detected}
    for fork in scan_unknown_chromium(deep_scan=deep_scan):
        if fork.policy_key in known_keys:
            fork.notes.append("Covered by the policy key above; nothing extra to write")
        detected.append(fork)
    return detected


def all_policy_targets(deep_scan: bool = True) -> list[DetectedBrowser]:
    """One entry per distinct policy key that should be written.

    Writing policy for a browser that is not installed costs nothing and means
    protection is already in force if that browser is installed later. Several
    browsers can share a key (every unbranded Chromium fork does), so this
    collapses them to avoid writing the same key twice.
    """
    targets: list[DetectedBrowser] = []
    seen: set[str] = set()
    for browser in detect_browsers(deep_scan=deep_scan):
        if browser.policy_key not in seen:
            targets.append(browser)
            seen.add(browser.policy_key)
    for defn in KNOWN_BROWSERS:
        if defn.policy_key not in seen:
            targets.append(
                DetectedBrowser(
                    definition=defn,
                    detected_via="preemptive",
                    notes=["Not installed; covered if it is installed later"],
                )
            )
            seen.add(defn.policy_key)
    return targets
