"""Entry point.

Double-clicking the executable opens the window. Passing any argument runs the
command line instead, so the same binary serves both.
"""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]

    wants_cli = bool(argv) and argv != ["--gui"]
    if wants_cli:
        from browserguard.cli import main as cli_main

        return cli_main(argv)

    try:
        from browserguard.gui.app import run
    except ImportError as exc:  # pragma: no cover - only when PySide6 is absent
        print(f"The graphical interface is unavailable ({exc}).")
        print("Run 'browserguard --help' to use the command line instead.")
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
