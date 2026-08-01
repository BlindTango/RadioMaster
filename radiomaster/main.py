"""Entry point for RadioMaster."""

from __future__ import annotations

from .app import RadioMasterApp


def main() -> None:
    app = RadioMasterApp()
    app.MainLoop()


if __name__ == "__main__":
    main()
