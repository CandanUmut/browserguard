"""Category blocklists bundled with the application.

Lists are plain text, one pattern per line, ``#`` for comments. They are shipped
inside the executable so the tool works with no network access at all.

A blocklist is an explicit list of domains, which by definition cannot cover
sites nobody has listed yet. That gap is closed separately by Chrome's
``SafeSitesFilterBehavior`` policy, which classifies pages server-side, and by
DNS-level filtering. See the README for how the layers fit together.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Category:
    """A bundled blocklist category."""

    id: str
    name: str
    description: str
    filename: str


CATEGORIES: tuple[Category, ...] = (
    Category(
        id="adult",
        name="Adult content",
        description="Pornography, cam sites and explicit imagery.",
        filename="adult.txt",
    ),
    Category(
        id="proxy",
        name="Proxies & VPNs",
        description=(
            "Circumvention tools. Worth blocking even on light settings, since "
            "these defeat every other filtering layer."
        ),
        filename="proxy.txt",
    ),
    Category(
        id="gambling",
        name="Gambling",
        description="Casinos, sportsbooks and betting sites.",
        filename="gambling.txt",
    ),
    Category(
        id="dating",
        name="Dating",
        description="Dating and hookup services.",
        filename="dating.txt",
    ),
    Category(
        id="social",
        name="Social media",
        description="Social networks. Often better suited to a schedule than a full block.",
        filename="social.txt",
    ),
    Category(
        id="gaming",
        name="Gaming",
        description="Game portals and launchers.",
        filename="gaming.txt",
    ),
    Category(
        id="streaming",
        name="Streaming",
        description="Video streaming services.",
        filename="streaming.txt",
    ),
)

CATEGORIES_BY_ID = {c.id: c for c in CATEGORIES}


def data_dir() -> Path:
    """Locate the bundled data directory, in source and in a PyInstaller build."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "browserguard" / "data" / "blocklists"
    return Path(__file__).resolve().parent.parent / "data" / "blocklists"


@lru_cache(maxsize=None)
def load_category(category_id: str) -> tuple[str, ...]:
    """Return the patterns in a bundled category, or an empty tuple if missing."""
    category = CATEGORIES_BY_ID.get(category_id)
    if category is None:
        return ()
    path = data_dir() / category.filename
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.append(line)
    return tuple(entries)


def category_size(category_id: str) -> int:
    """Number of patterns in a category."""
    return len(load_category(category_id))


def expand_categories(category_ids: list[str]) -> list[str]:
    """Flatten several categories into one de-duplicated, ordered pattern list."""
    seen: set[str] = set()
    result: list[str] = []
    for cid in category_ids:
        for pattern in load_category(cid):
            if pattern not in seen:
                seen.add(pattern)
                result.append(pattern)
    return result


def normalise_pattern(raw: str) -> str:
    """Tidy user input into a Chromium URLBlocklist pattern.

    Chromium accepts a bare host (blocking it and its subdomains), so the scheme,
    ``www.`` prefix and any path are stripped to keep entries predictable.
    """
    pattern = raw.strip()
    if not pattern:
        return ""
    for scheme in ("https://", "http://"):
        if pattern.lower().startswith(scheme):
            pattern = pattern[len(scheme) :]
    pattern = pattern.split("/")[0]
    if pattern.lower().startswith("www."):
        pattern = pattern[4:]
    return pattern.strip().lower()
