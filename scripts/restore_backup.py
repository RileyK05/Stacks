from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.backend.common.backups import BackupError, _restore_into


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore a Stacks backup into a new, empty data folder."
    )
    parser.add_argument("archive", type=Path, help="backup .zip file")
    parser.add_argument("destination", type=Path, help="new empty data folder")
    args = parser.parse_args()
    try:
        _restore_into(args.archive, args.destination)
    except (BackupError, OSError, ValueError) as error:
        print(f"Restore failed: {error}", file=sys.stderr)
        return 2
    print(f"Restored data folder: {args.destination.resolve()}")
    print("The active library was not changed. Close Stacks before manual activation.")
    print("The installed desktop app cannot switch data folders from Settings yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
