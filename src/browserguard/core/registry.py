r"""Registry access, behind a small interface so the core is testable off-Windows.

Everything BrowserGuard writes lives under HKEY_LOCAL_MACHINE. Paths are passed
as strings relative to HKLM, e.g. ``SOFTWARE\Policies\Google\Chrome``.
"""

from __future__ import annotations

import sys
from typing import Protocol

from browserguard.core.errors import PrivilegeError, RegistryError

REG_SZ = "sz"
REG_DWORD = "dword"

IS_WINDOWS = sys.platform == "win32"


class Registry(Protocol):
    """The registry operations the core needs."""

    def set_value(self, key: str, name: str, value: object, kind: str) -> None: ...

    def get_value(self, key: str, name: str) -> object | None: ...

    def delete_value(self, key: str, name: str) -> None: ...

    def delete_tree(self, key: str) -> None: ...

    def list_values(self, key: str) -> dict[str, object]: ...

    def key_exists(self, key: str) -> bool: ...


class MemoryRegistry:
    """In-memory registry used by the test suite and by ``--dry-run``."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, object]] = {}

    def set_value(self, key: str, name: str, value: object, kind: str) -> None:
        self.data.setdefault(key, {})[name] = value

    def get_value(self, key: str, name: str) -> object | None:
        return self.data.get(key, {}).get(name)

    def delete_value(self, key: str, name: str) -> None:
        self.data.get(key, {}).pop(name, None)

    def delete_tree(self, key: str) -> None:
        prefix = key.rstrip("\\") + "\\"
        for existing in [k for k in self.data if k == key or k.startswith(prefix)]:
            del self.data[existing]

    def list_values(self, key: str) -> dict[str, object]:
        return dict(self.data.get(key, {}))

    def key_exists(self, key: str) -> bool:
        prefix = key.rstrip("\\") + "\\"
        return key in self.data or any(k.startswith(prefix) for k in self.data)


class WindowsRegistry:
    """Real HKLM access via :mod:`winreg`."""

    def __init__(self) -> None:
        if not IS_WINDOWS:  # pragma: no cover - guarded by caller
            raise RegistryError("WindowsRegistry requires Windows")
        import winreg

        self._winreg = winreg
        self._root = winreg.HKEY_LOCAL_MACHINE

    def _kind(self, kind: str) -> int:
        return self._winreg.REG_DWORD if kind == REG_DWORD else self._winreg.REG_SZ

    def set_value(self, key: str, name: str, value: object, kind: str) -> None:
        try:
            with self._winreg.CreateKeyEx(
                self._root, key, 0, self._winreg.KEY_SET_VALUE | self._winreg.KEY_WOW64_64KEY
            ) as handle:
                self._winreg.SetValueEx(handle, name, 0, self._kind(kind), value)
        except PermissionError as exc:
            raise PrivilegeError(
                f"Administrator rights are required to write {key}"
            ) from exc
        except OSError as exc:
            raise RegistryError(f"Could not write {key}\\{name}: {exc}") from exc

    def get_value(self, key: str, name: str) -> object | None:
        try:
            with self._winreg.OpenKey(
                self._root, key, 0, self._winreg.KEY_READ | self._winreg.KEY_WOW64_64KEY
            ) as handle:
                value, _ = self._winreg.QueryValueEx(handle, name)
                return value
        except FileNotFoundError:
            return None
        except OSError:
            return None

    def delete_value(self, key: str, name: str) -> None:
        try:
            with self._winreg.OpenKey(
                self._root, key, 0, self._winreg.KEY_SET_VALUE | self._winreg.KEY_WOW64_64KEY
            ) as handle:
                self._winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            return
        except PermissionError as exc:
            raise PrivilegeError(f"Administrator rights are required to edit {key}") from exc
        except OSError:
            return

    def delete_tree(self, key: str) -> None:
        for child in self._subkeys(key):
            self.delete_tree(f"{key}\\{child}")
        try:
            self._winreg.DeleteKeyEx(self._root, key, self._winreg.KEY_WOW64_64KEY, 0)
        except FileNotFoundError:
            return
        except PermissionError as exc:
            raise PrivilegeError(f"Administrator rights are required to delete {key}") from exc
        except OSError:
            return

    def _subkeys(self, key: str) -> list[str]:
        names: list[str] = []
        try:
            with self._winreg.OpenKey(
                self._root, key, 0, self._winreg.KEY_READ | self._winreg.KEY_WOW64_64KEY
            ) as handle:
                index = 0
                while True:
                    try:
                        names.append(self._winreg.EnumKey(handle, index))
                        index += 1
                    except OSError:
                        break
        except OSError:
            return []
        return names

    def list_values(self, key: str) -> dict[str, object]:
        values: dict[str, object] = {}
        try:
            with self._winreg.OpenKey(
                self._root, key, 0, self._winreg.KEY_READ | self._winreg.KEY_WOW64_64KEY
            ) as handle:
                index = 0
                while True:
                    try:
                        name, value, _ = self._winreg.EnumValue(handle, index)
                        values[name] = value
                        index += 1
                    except OSError:
                        break
        except OSError:
            return {}
        return values

    def key_exists(self, key: str) -> bool:
        try:
            with self._winreg.OpenKey(
                self._root, key, 0, self._winreg.KEY_READ | self._winreg.KEY_WOW64_64KEY
            ):
                return True
        except OSError:
            return False


def default_registry() -> Registry:
    """Return the real registry on Windows, an in-memory stand-in elsewhere."""
    return WindowsRegistry() if IS_WINDOWS else MemoryRegistry()


def is_admin() -> bool:
    """True when the current process holds administrator rights."""
    if not IS_WINDOWS:
        return False
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # pragma: no cover - defensive
        return False
