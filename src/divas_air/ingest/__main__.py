"""CLI: python -m divas_air.ingest --source <fco|baltic|control|adr_mock|lira|all>."""

from __future__ import annotations

import argparse
import sys

from divas_air.ingest import ALL_SOURCES, _ingest, source_files, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m divas_air.ingest")
    ap.add_argument("--source", required=True, choices=(*ALL_SOURCES, "all"))
    args = ap.parse_args(argv)

    if args.source == "all":
        sources = [s for s in ALL_SOURCES if source_files(s)]
        for s in ALL_SOURCES:
            if s not in sources:
                print(f"{s}: no input data, skipped")
    else:
        sources = [args.source]

    for s in sources:
        path, points, drops = _ingest(s)
        print(summary(s, points, drops), "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
