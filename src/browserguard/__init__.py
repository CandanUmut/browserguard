"""BrowserGuard - browser-level parental controls for Windows.

Applies enterprise browser policy (the same mechanism IT departments use) to
every browser installed on the machine, so filtering is enforced by the browser
itself rather than by DNS.
"""

from browserguard.version import APP_NAME, __version__

__all__ = ["__version__", "APP_NAME"]
