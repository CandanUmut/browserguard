"""Passcode generation, hashing and export.

The passcode does one thing: it skips the cooldown wait. It is never required to
open the app, view settings, or make a change. Losing it costs you nothing but
time, which is what keeps this a parental control rather than a lockout.

Only a salted PBKDF2 hash is stored. The plaintext exists in the exported text
file, which is the copy meant to be kept or shared.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from pathlib import Path

# Digits and letters that cannot be confused when read aloud or written down:
# no 0/O, 1/I/L, 5/S, 8/B.
_ALPHABET = "ACDEFGHJKMNPQRTUVWXYZ234679"
_GROUP_SIZE = 4
_GROUPS = 4

_PBKDF2_ROUNDS = 240_000


def generate_passcode() -> str:
    """Create a new random passcode, formatted for reading aloud."""
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_SIZE))
        for _ in range(_GROUPS)
    ]
    return "-".join(groups)


def normalise(passcode: str) -> str:
    """Accept a passcode typed with any spacing or casing."""
    return passcode.replace("-", "").replace(" ", "").strip().upper()


def hash_passcode(passcode: str, salt: str | None = None) -> tuple[str, str]:
    """Return ``(hash_hex, salt_hex)`` for a passcode."""
    salt_hex = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalise(passcode).encode("utf-8"),
        bytes.fromhex(salt_hex),
        _PBKDF2_ROUNDS,
    )
    return digest.hex(), salt_hex


def verify_passcode(passcode: str, hash_hex: str, salt_hex: str) -> bool:
    """Check a passcode against a stored hash in constant time."""
    if not passcode or not hash_hex or not salt_hex:
        return False
    try:
        candidate, _ = hash_passcode(passcode, salt_hex)
    except ValueError:
        return False
    return hmac.compare_digest(candidate, hash_hex)


def export_passcode(passcode: str, destination: Path, machine_name: str = "") -> Path:
    """Write the passcode to a text file the owner can store or hand to someone."""
    created = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    machine_line = f"Computer:   {machine_name}\n" if machine_name else ""
    contents = (
        "BrowserGuard passcode\n"
        "=====================\n\n"
        f"Passcode:   {passcode}\n"
        f"{machine_line}"
        f"Created:    {created}\n\n"
        "What this is for\n"
        "----------------\n"
        "This passcode skips the waiting period when protection is being\n"
        "reduced. It is not needed to open BrowserGuard, to view settings,\n"
        "or to make protection stronger.\n\n"
        "If you lose it, nothing is locked. Any change still goes through\n"
        "once the waiting period has passed on its own.\n\n"
        "Keep this file somewhere separate from the computer it protects -\n"
        "give it to a partner, a friend, or store it in a password manager.\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(contents, encoding="utf-8")
    return destination
