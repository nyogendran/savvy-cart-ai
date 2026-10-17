"""The committed purchase history is de-identified, whitelisted, and adds up."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "samples" / "purchase-history.json"
FICTIONAL = ROOT / "fixtures" / "v2" / "history-fictional.json"

BILL_KEYS = {"date", "chain", "source", "lines", "promotions", "card_offers", "gross_lkr", "net_lkr"}
LINE_KEYS = {"line", "raw", "qty", "unit_lkr", "amount_lkr"}
PROMOTION_KEYS = {"label", "line", "rate_bps", "amount_lkr"}
CARD_OFFER_KEYS = {"bank", "rate_bps", "category", "amount_lkr"}
CHAINS = {"keells", "cargills", "spar", "glomark"}
# Product text prints in capitals; these are the only mixed-case item names the stores print.
MIXED_CASE_ITEMS = {"Large Polythene Bag", "Medium Polythene Bag", "Small Polythene Bag"}
FORBIDDEN = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"https?://|mail\.google|www\."),
    re.compile(r"\b\d{6,}\b"),
    re.compile(r"\b(?:Bill No|Nexus No|Cashier ID|Store Mobile|Store Address|Billed Store|Mawatha)\b", re.IGNORECASE),
]


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["bills"]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_history_is_deidentified():
    real, fictional = _load(REAL), _load(FICTIONAL)
    assert len(real) >= 20 and len(fictional) >= 10
    assert {b["source"] for b in real} == {"receipt"} and {b["chain"] for b in real} == {"keells"}
    assert {b["source"] for b in fictional} == {"fictional"}
    assert {"cargills", "glomark"} <= {b["chain"] for b in fictional}

    for bill in real + fictional:
        assert set(bill) == BILL_KEYS
        date.fromisoformat(bill["date"])
        assert bill["chain"] in CHAINS
        assert isinstance(bill["gross_lkr"], int) and isinstance(bill["net_lkr"], int)
        for line in bill["lines"]:
            assert set(line) == LINE_KEYS
            assert isinstance(line["unit_lkr"], int) and isinstance(line["amount_lkr"], int)
            assert isinstance(line["qty"], (int, float)) and line["qty"] > 0
            if re.search(r"[a-z]", line["raw"]):
                assert line["raw"] in MIXED_CASE_ITEMS, f"unexpected mixed-case item text on {bill['date']}"
        for promotion in bill["promotions"]:
            assert set(promotion) == PROMOTION_KEYS
            assert isinstance(promotion["rate_bps"], int) and isinstance(promotion["amount_lkr"], int)
        for offer in bill["card_offers"]:
            assert set(offer) == CARD_OFFER_KEYS
            assert isinstance(offer["rate_bps"], int) and isinstance(offer["amount_lkr"], int)

    for path in (REAL, FICTIONAL):
        text = path.read_text(encoding="utf-8")
        document = json.loads(text)
        for value in _strings(document):
            for pattern in FORBIDDEN:
                assert not pattern.search(value), f"{path.name}: forbidden pattern {pattern.pattern}"


def test_bill_lines_sum_to_gross():
    for bill in _load(REAL) + _load(FICTIONAL):
        total = sum(line["amount_lkr"] for line in bill["lines"])
        assert abs(total - bill["gross_lkr"]) <= len(bill["lines"]), bill["date"]
        discounts = bill["promotions"] + bill["card_offers"]
        promoted = sum(p["amount_lkr"] for p in discounts)
        assert bill["net_lkr"] <= bill["gross_lkr"]
        assert abs(bill["gross_lkr"] - promoted - bill["net_lkr"]) <= len(discounts) + 1, bill["date"]
