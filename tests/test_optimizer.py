"""Optimizer acceptance tests for SC-003 (committed fixtures only)."""

from __future__ import annotations

import json
from pathlib import Path

from savvycart.optimizer import optimize

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _catalog_offers():
    return _load("catalog.json"), _load("offers.json")["offers"]


def test_under_minimum_savings_are_zero():
    catalog, offers = _catalog_offers()
    basket = _load("baskets/refused.json")
    result = optimize(
        catalog,
        offers,
        basket["lines"],
        {"weekday": "saturday", "date": "2026-10-17"},
        usual_store="keells",
    )
    assert result["winner"] is not None
    assert all(plan["discount"] == 0 for plan in result["plans"])


def test_cap_limits_discount():
    catalog, offers = _catalog_offers()
    basket = _load("baskets/capped.json")
    result = optimize(
        catalog,
        offers,
        basket["lines"],
        {"weekday": "saturday", "date": "2026-10-17"},
        usual_store="keells",
    )
    winner = result["winner"]
    assert winner is not None
    assert winner["store_id"] == "keells"
    assert winner["discount"] == 1000
    assert winner["discount"] == next(o["cap_lkr"] for o in offers if o["id"] == "keells_saturday")
    assert winner["discount"] < winner["naive_discount"]


def test_day_sweep_saturday_cap_thursday_zero():
    catalog, offers = _catalog_offers()
    basket = _load("baskets/capped.json")
    sat = optimize(
        catalog,
        offers,
        basket["lines"],
        {"weekday": "saturday", "date": "2026-10-17"},
        usual_store="keells",
    )
    thu = optimize(
        catalog,
        offers,
        basket["lines"],
        {"weekday": "thursday", "date": "2026-10-15"},
        usual_store="keells",
    )
    sat_keells = next(p for p in sat["plans"] if p["store_id"] == "keells")
    thu_keells = next(p for p in thu["plans"] if p["store_id"] == "keells")
    assert sat_keells["discount"] == 1000
    assert thu_keells["discount"] == 0
    assert sat_keells["shelf_total"] == thu_keells["shelf_total"]
    assert sat_keells["eligible_subtotal"] == thu_keells["eligible_subtotal"] == 8500


def test_expired_offer_saves_zero():
    catalog, offers = _catalog_offers()
    basket = _load("baskets/capped.json")
    result = optimize(
        catalog,
        offers,
        basket["lines"],
        {"weekday": "saturday", "date": "2026-11-01"},
        usual_store="keells",
    )
    keells = next(p for p in result["plans"] if p["store_id"] == "keells")
    assert keells["discount"] == 0
    assert keells["reason"] == "expired"
