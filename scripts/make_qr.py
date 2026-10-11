"""QR code for the public demo link (shown under Demos > Share, and for the last pitch slide).

    python scripts/make_qr.py [url]   ->  app/web/qr.png  (+ a large reports-ready copy, qr_large.png)
"""

import sys
from pathlib import Path

import segno

URL = sys.argv[1] if len(sys.argv) > 1 else "https://ivajefremova.github.io/divas_air/"
WEB = Path(__file__).resolve().parents[1] / "app" / "web"

if __name__ == "__main__":
    qr = segno.make(URL, error="m")
    qr.save(WEB / "qr.png", scale=8, border=2, dark="#18203a")
    qr.save(WEB / "qr_large.png", scale=24, border=3, dark="#18203a")
    print(f"QR for {URL} -> {WEB / 'qr.png'} and qr_large.png")
