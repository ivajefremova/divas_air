"""CLI: python -m divas_air.adr [--synthetic-eval]."""

from __future__ import annotations

import argparse
import json


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m divas_air.adr")
    ap.add_argument(
        "--synthetic-eval", action="store_true", help="detector P/R on generator events"
    )
    a = ap.parse_args(argv)
    if a.synthetic_eval:
        from divas_air.adr.synth_eval import run
    else:
        from divas_air.adr.score import run
    print(json.dumps(run(), indent=2, default=str))


if __name__ == "__main__":
    main()
