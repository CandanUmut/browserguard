"""macOS policy storage.

Browsers on macOS read managed policy from property lists in
``/Library/Managed Preferences``, keyed by the application's bundle identifier,
e.g. ``com.google.Chrome.plist``. The policy *names* are identical to the Windows
ones, so only the storage differs.

This module presents the same interface as the Windows registry backend, with a
key path of ``com.google.Chrome\\URLBlocklist`` mapping onto nested structure
inside that bundle's plist. Writing there needs root, the same way the Windows
side needs administrator rights.

Beta: this backend is implemented against Chromium's and Firefox's documented
macOS policy behaviour but has had far less real-world exercise than the Windows
path.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from browserguard.core.errors import PrivilegeError, RegistryError
from browserguard.core.registry import REG_BOOL, REG_DWORD

MANAGED_PREFERENCES = Path("/Library/Managed Preferences")


def _split(key: str) -> tuple[str, list[str]]:
    """Split ``com.google.Chrome\\URLBlocklist`` into domain and nested path."""
    parts = [p for p in key.replace("/", "\\").split("\\") if p]
    if not parts:
        raise RegistryError(f"Invalid policy key: {key!r}")
    return parts[0], parts[1:]


def _to_native(value: object, kind: str) -> object:
    if kind == REG_BOOL:
        return bool(value)
    if kind == REG_DWORD:
        return int(value)
    return value


def _numeric_dict_to_list(node: object) -> object:
    """Chromium list policies are stored here as ``{"1": ..., "2": ...}``.

    Property lists want a real array, so any node whose keys are all digits is
    converted, in numeric order.
    """
    if isinstance(node, dict):
        if node and all(k.isdigit() for k in node):
            return [_numeric_dict_to_list(node[k]) for k in sorted(node, key=int)]
        return {k: _numeric_dict_to_list(v) for k, v in node.items()}
    return node


class PlistRegistry:
    """Managed-preference storage that mirrors the registry interface."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or MANAGED_PREFERENCES

    # -- file helpers ---------------------------------------------------
    def _path(self, domain: str) -> Path:
        return self.root / f"{domain}.plist"

    def _load(self, domain: str) -> dict:
        path = self._path(domain)
        if not path.exists():
            return {}
        try:
            with path.open("rb") as handle:
                data = plistlib.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, plistlib.InvalidFileException):
            return {}

    def _save(self, domain: str, data: dict) -> None:
        path = self._path(domain)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = _numeric_dict_to_list(data)
            temp = path.with_suffix(".plist.tmp")
            with temp.open("wb") as handle:
                plistlib.dump(payload, handle)
            temp.replace(path)
        except PermissionError as exc:
            raise PrivilegeError(
                f"Root access is required to write {path}. Run BrowserGuard with sudo."
            ) from exc
        except OSError as exc:
            raise RegistryError(f"Could not write {path}: {exc}") from exc

    # -- registry interface ---------------------------------------------
    def set_value(self, key: str, name: str, value: object, kind: str) -> None:
        domain, path = _split(key)
        data = self._load(domain)
        node = data
        for segment in path:
            child = node.get(segment)
            if not isinstance(child, dict):
                # A list read back from a plist has to become a dict again so a
                # numbered entry can be addressed by name.
                if isinstance(child, list):
                    child = {str(i + 1): v for i, v in enumerate(child)}
                else:
                    child = {}
                node[segment] = child
            node = child
        node[name] = _to_native(value, kind)
        self._save(domain, data)

    def get_value(self, key: str, name: str) -> object | None:
        domain, path = _split(key)
        node: object = self._load(domain)
        for segment in path:
            if not isinstance(node, dict):
                return None
            node = node.get(segment)
        if isinstance(node, dict):
            return node.get(name)
        if isinstance(node, list) and name.isdigit():
            index = int(name) - 1
            return node[index] if 0 <= index < len(node) else None
        return None

    def delete_value(self, key: str, name: str) -> None:
        domain, path = _split(key)
        data = self._load(domain)
        node: object = data
        for segment in path:
            if not isinstance(node, dict):
                return
            node = node.get(segment)
        if isinstance(node, dict) and name in node:
            del node[name]
            self._save(domain, data)

    def delete_tree(self, key: str) -> None:
        domain, path = _split(key)
        if not path:
            target = self._path(domain)
            try:
                target.unlink(missing_ok=True)
            except PermissionError as exc:
                raise PrivilegeError(f"Root access is required to remove {target}") from exc
            except OSError:
                return
            return
        data = self._load(domain)
        node: object = data
        for segment in path[:-1]:
            if not isinstance(node, dict):
                return
            node = node.get(segment)
        if isinstance(node, dict) and path[-1] in node:
            del node[path[-1]]
            self._save(domain, data)

    def list_values(self, key: str) -> dict[str, object]:
        domain, path = _split(key)
        node: object = self._load(domain)
        for segment in path:
            if not isinstance(node, dict):
                return {}
            node = node.get(segment)
        if isinstance(node, list):
            return {str(i + 1): v for i, v in enumerate(node)}
        if isinstance(node, dict):
            # Only scalar leaves belong in a value listing.
            return {k: v for k, v in node.items() if not isinstance(v, (dict, list))}
        return {}

    def key_exists(self, key: str) -> bool:
        domain, path = _split(key)
        node: object = self._load(domain)
        if not path:
            return bool(node)
        for segment in path:
            if not isinstance(node, dict) or segment not in node:
                return False
            node = node[segment]
        return True
