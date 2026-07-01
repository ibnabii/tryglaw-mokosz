"""CLI for Mokosz administration.

Usage:
    python -m tryglaw.mokosz.admin_cli generate-key
"""
from __future__ import annotations

import sys

from tryglaw.common.security import generate_api_key


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    command = args[0]
    if command == "generate-key":
        print(generate_api_key())
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
