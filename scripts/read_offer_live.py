"""Manual live check: Gemini reads the sample bank offer text; compare its terms with the checked-in reading.

Never run in CI. Needs the same environment as scripts/extract_receipt_live.py.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIELDS = ["store_name", "percent_off", "days", "minimum_bill_lkr", "max_discount_lkr", "max_units_per_item",
          "combines_with_store_offers", "valid_until"]


def main() -> int:
    from extract_receipt_live import missing_credentials

    missing = missing_credentials()
    if missing:
        print("missing: " + ", ".join(missing), file=sys.stderr)
        return 2
    from savvycart.gemini import GeminiModelClient
    from savvycart.offercheck import OFFER_PROMPT, OFFER_SCHEMA, validate_rule

    sample = json.loads((ROOT / "fixtures/v2/offer-sample-seylan.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "fixtures/v2/catalog.json").read_text(encoding="utf-8"))
    started = time.monotonic()
    raw = GeminiModelClient(os.environ["GEMINI_MODEL"]).extract_offer(sample["text"], None, OFFER_SCHEMA, OFFER_PROMPT)
    seconds = time.monotonic() - started
    expected = sample["extracted"]
    mismatches = [f"{k}: got {raw.get(k)!r}, expected {expected.get(k)!r}" for k in FIELDS if raw.get(k) != expected.get(k)]
    rule, notes = validate_rule(raw, catalog, "gemini")
    print(f"model {os.environ['GEMINI_MODEL']}, {seconds:.1f} s")
    print("excluded catalog items:", rule["exclude_sku_ids"] if rule else "rule refused", "| notes:", notes)
    print("\n".join(mismatches) if mismatches else "all checked fields match")
    return 0 if rule and not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
