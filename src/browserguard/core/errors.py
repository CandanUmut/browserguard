"""Exception types raised by the BrowserGuard core."""


class BrowserGuardError(Exception):
    """Base class for all BrowserGuard errors."""


class PrivilegeError(BrowserGuardError):
    """Raised when an operation needs administrator rights and does not have them."""


class RegistryError(BrowserGuardError):
    """Raised when a registry read or write fails."""


class ConfigError(BrowserGuardError):
    """Raised when stored configuration cannot be read or is invalid."""


class CooldownError(BrowserGuardError):
    """Raised when a change is blocked by an active cooldown."""
