"""Guardrails: instruction/injection text must not change discounts."""

from __future__ import annotations

import json
from pathlib import Path

from savvycart.optimizer import optimize

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_injection_text_does_not_change_discount():
    catalog = _load("catalog.json")
    offers = _load("offers.json")["offers"]
    capped = _load("baskets/capped.json")["lines"]
    injection = _load("receipt-injection.json")["lines"]
    day = {"weekday": "saturday", "date": "2026-10-17"}

    clean = optimize(catalog, offers, capped, day, usual_store="keells")
    poisoned = optimize(catalog, offers, injection, day, usual_store="keells")

    assert clean["winner"]["discount"] == poisoned["winner"]["discount"]
    clean_by_store = {p["store_id"]: p["discount"] for p in clean["plans"]}
    poisoned_by_store = {p["store_id"]: p["discount"] for p in poisoned["plans"]}
    assert clean_by_store == poisoned_by_store
