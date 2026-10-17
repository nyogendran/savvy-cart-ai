"""Pantry cadence from purchase dates, and v2 fixture labeling."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from savvycart.pantry import pantry

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "fixtures" / "v2"
TODAY = date(2026, 10, 18)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _history():
    return _json(ROOT / "samples" / "purchase-history.json")["bills"] + _json(V2 / "history-fictional.json")["bills"]


def _by_sku(items):
    return {item["sku_id"]: item for item in items}


def _bill(day: str, raw: str, qty: float = 1.0) -> dict:
    return {"date": day, "chain": "keells", "source": "fictional", "lines": [{"line": 1, "raw": raw, "qty": qty, "unit_lkr": 100, "amount_lkr": 100}],
            "promotions": [], "card_offers": [], "gross_lkr": 100, "net_lkr": 100}


def test_cadence_and_status_follow_history():
    catalog, history_map = _json(V2 / "catalog.json"), _json(V2 / "history-map.json")
    items = _by_sku(pantry(_history(), catalog, history_map, TODAY))

    # Seventeen purchase dates; sorted gaps have median (7 + 8) / 2 = 7.5, rounded half up to 8.
    banana = items["banana_ambul"]
    assert banana["purchase_dates"] == 17
    assert banana["cadence_days"] == 8
    assert banana["last_bought"] == "2026-10-17"
    assert banana["next_due"] == "2026-10-25"
    assert banana["days_left"] == 7
    assert banana["status"] == "soon"
    assert "every 8 days" in banana["reason"] and "2026-10-25" in banana["reason"]

    # Last bought 27 Sep with a six-day cadence: overdue, and eight dates allow "due".
    assert items["tea_bun"]["status"] == "due" and items["tea_bun"]["days_left"] < 0
    assert {i["status"] for i in items.values()} <= {"due", "soon", "ok", "unknown"}

    # Threshold rules on a small synthetic history.
    tiny = {"skus": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}, {"id": "c", "name": "C"}]}
    tiny_map = {"A": "a", "B": "b", "C": "c"}
    bills = [
        _bill("2026-10-01", "A"), _bill("2026-10-08", "A"), _bill("2026-10-15", "A"),  # three dates, due 22 Oct
        _bill("2026-10-08", "B"), _bill("2026-10-15", "B"),                             # two dates, would be due
        _bill("2026-10-15", "C"),                                                       # one date
    ]
    result = _by_sku(pantry(bills, tiny, tiny_map, date(2026, 10, 20)))
    assert result["a"]["cadence_days"] == 7 and result["a"]["days_left"] == 2 and result["a"]["status"] == "due"
    assert result["b"]["days_left"] == 2 and result["b"]["status"] == "soon"
    assert result["c"]["status"] == "unknown"


def test_v2_fixtures_are_labeled_and_in_band():
    catalog = _json(V2 / "catalog.json")
    offers = _json(V2 / "offers.json")
    history_map = _json(V2 / "history-map.json")
    stores = set(catalog["stores"])
    assert stores == {"keells", "cargills", "spar", "glomark"}

    keells_wins = keells_loses = 0
    for sku in catalog["skus"]:
        assert sku["category"] in {"staple", "fresh", "household"}
        keells = sku["prices"]["keells"]
        assert keells["source"] == "receipt" and date.fromisoformat(keells["observed_on"])
        others = {s: p for s, p in sku["prices"].items() if s != "keells"}
        assert set(others) == stores - {"keells"}
        for price in others.values():
            assert price["source"] == "fictional"
            assert abs(price["amount_lkr"] - keells["amount_lkr"]) <= keells["amount_lkr"] * 0.10
        cheapest = min(sku["prices"].values(), key=lambda p: p["amount_lkr"])["amount_lkr"]
        keells_wins += keells["amount_lkr"] == cheapest
        keells_loses += keells["amount_lkr"] > cheapest
    assert keells_wins > 0 and keells_loses > 0

    sku_ids = {sku["id"] for sku in catalog["skus"]}
    assert set(history_map.values()) <= sku_ids
    assert {o["bank"] for o in offers["card_offers"]} == {"Commercial Bank", "Nations Trust Bank", "HNB"}
    for offer in offers["card_offers"]:
        assert offer["store_id"] in stores and offer["stackable"] is False
        assert date.fromisoformat(offer["valid_to"])
        if offer["source"] == "fictional":
            assert offer["note"] == "Demo shape. Not a live bank or store promotion."
        else:  # SC-019: published headlines carry their source; unpublished terms are assumptions
            assert offer["source"] == "published" and offer["source_url"].startswith("https://")
            assert offer["terms_source"] == "assumption"
    for promotion in offers["store_promotions"]:
        assert promotion["store_id"] in stores
        assert ("sku_id" in promotion) != ("category" in promotion)
        assert promotion["note"] == "Demo shape. Not a live bank or store promotion."
        if promotion.get("type") == "fixed_price":
            assert promotion["price_lkr"] > 0 and promotion["max_qty"] >= 1
