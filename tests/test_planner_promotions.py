"""Fixed-price multi-buy promotions and plans across up to four stores (SC-019 AC7, AC9)."""

from __future__ import annotations

import pytest

from savvycart.planner import plan_day

ALL_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY = "2026-10-24"


def _price(amount: int) -> dict:
    return {"amount_lkr": amount, "source": "fictional", "observed_on": "2026-10-17"}


def _milk_catalog() -> dict:
    return {"stores": ["c"], "skus": [{"id": "milk", "name": "Milk 1 L", "category": "staple", "prices": {"c": _price(580)}}]}


def _offers(percent_bps: int) -> dict:
    return {
        "store_promotions": [
            {"id": "c_milk_fixed", "type": "fixed_price", "store_id": "c", "sku_id": "milk", "price_lkr": 500, "max_qty": 3,
             "days": ALL_DAYS, "valid_to": "2026-10-31"},
            {"id": "c_milk_percent", "store_id": "c", "sku_id": "milk", "rate_bps": percent_bps, "days": ALL_DAYS, "valid_to": "2026-10-31"},
        ],
        "card_offers": [
            {"id": "c_card", "bank": "Bank One", "product": "credit", "store_id": "c", "days": ALL_DAYS, "rate_bps": 1000,
             "min_bill_lkr": 1000, "cap_lkr": 1000, "include_categories": ["staple"], "exclude_categories": [],
             "valid_to": "2026-10-31", "stackable": False},
        ],
    }


def test_fixed_price_multibuy_limit():
    plan = plan_day(_milk_catalog(), _offers(1000), [{"sku_id": "milk", "qty": 4}], DAY, ["Bank One"], max_stores=1, trip_cost_lkr=0, usual_store="c")
    (line,) = plan["stores"][0]["lines"]
    # 3 units at 500 and the fourth at shelf 580; the 10% promotion would save only 232, and the two never stack.
    assert line["shelf_lkr"] == 2320 and line["promoted_lkr"] == 3 * 500 + 580 and line["promo_saving_lkr"] == 240
    assert line["promo_id"] == "c_milk_fixed"
    bill = plan["stores"][0]
    assert bill["card_discount_lkr"] == (2080 * 1000) // 10000 and bill["bill_lkr"] == 2080 - 208
    assert plan["solver_status"] == "OPTIMAL"

    better_percent = plan_day(_milk_catalog(), _offers(2000), [{"sku_id": "milk", "qty": 4}], DAY, ["Bank One"], max_stores=1, trip_cost_lkr=0, usual_store="c")
    (line,) = better_percent["stores"][0]["lines"]
    assert line["promo_id"] == "c_milk_percent" and line["promo_saving_lkr"] == 464


def _four_store_catalog() -> dict:
    cheap = {"x": "a", "y": "b", "z": "c"}
    skus = []
    for sku_id, home in cheap.items():
        skus.append({"id": sku_id, "name": sku_id.upper(), "category": "staple",
                     "prices": {s: _price(500 if s == home else 1000) for s in ("a", "b", "c", "d")}})
    return {"stores": ["a", "b", "c", "d"], "skus": skus}


def test_up_to_four_stores():
    basket = [{"sku_id": s, "qty": 1} for s in ("x", "y", "z")]
    catalog = _four_store_catalog()
    three = plan_day(catalog, {}, basket, DAY, [], max_stores=4, trip_cost_lkr=100, usual_store="d")
    assert three["solver_status"] == "OPTIMAL" and sorted(b["store_id"] for b in three["stores"]) == ["a", "b", "c"]
    assert three["effective_cost_lkr"] == 3 * 500 + 2 * 100
    two = plan_day(catalog, {}, basket, DAY, [], max_stores=2, trip_cost_lkr=100, usual_store="d")
    assert len(two["stores"]) <= 2 and two["effective_cost_lkr"] > three["effective_cost_lkr"]
    with pytest.raises(ValueError):
        plan_day(catalog, {}, basket, DAY, [], max_stores=5, trip_cost_lkr=100, usual_store="d")
