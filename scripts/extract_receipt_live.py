"""Manual live check: send a receipt photo to Gemini and compare with a transcription.

Never run in CI. Needs GEMINI_MODEL plus GEMINI_API_KEY or GOOGLE_API_KEY
(or GOOGLE_GENAI_USE_VERTEXAI=true with GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_IMAGE = ROOT / "samples/receipts/keells-2026-10-17-redacted.jpg"
DEFAULT_EXPECTED = ROOT / "samples/receipts/keells-2026-10-17.expected.json"


def missing_credentials() -> list[str]:
    missing = []
    if not os.environ.get("GEMINI_MODEL"):
        missing.append("GEMINI_MODEL")
    has_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true"
    if not (has_key or vertex):
        missing.append("GEMINI_API_KEY (or GOOGLE_API_KEY, or GOOGLE_GENAI_USE_VERTEXAI=true)")
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE))
    parser.add_argument("--expected", default=str(DEFAULT_EXPECTED))
    args = parser.parse_args(argv)

    missing = missing_credentials()
    if missing:
        print("Missing environment: " + ", ".join(missing), file=sys.stderr)
        return 2

    from savvycart.gemini import GeminiModelClient
    from savvycart.receipts import RECEIPT_LINES_SCHEMA

    result = GeminiModelClient(os.environ["GEMINI_MODEL"]).extract(
        Path(args.image).read_bytes(), RECEIPT_LINES_SCHEMA
    )
    lines = result["lines"]
    for line in lines:
        print(f'{line["confidence"]:.2f}  {str(line["sku_id"]):<20} x{line["qty"]}  {line["raw"]}')

    expected_path = Path(args.expected)
    if expected_path.exists():
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        want = sorted(l["expected_sku_id"] for l in expected["lines"] if l["expected_sku_id"])
        got = sorted(l["sku_id"] for l in lines if l["sku_id"])
        print(f'\nlines: got {len(lines)}, expected {len(expected["lines"])}')
        print(f"sku matches: {sorted(set(want) & set(got))}")
        print(f"expected skus missed: {sorted(set(want) - set(got))}")
        print(f"unexpected skus: {sorted(set(got) - set(want))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
