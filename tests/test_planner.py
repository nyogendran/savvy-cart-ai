"""Day planner rules on small hand-checkable stores, plus the day sweep on real fixtures."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from savvycart.pantry import pantry
from savvycart.planner import day_sweep, plan_day

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "fixtures" / "v2"
ALL_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY = "2026-10-24"  # a Saturday


def _catalog(prices_b=None):
    prices_b = prices_b or {"s1": 1100, "f1": 1000, "f2": 1000}
    a = {"s1": 1000, "f1": 1000, "f2": 1000}

    def price(amount):
        return {"amount_lkr": amount, "source": "fictional", "observed_on": "2026-10-17"}

    return {
        "stores": ["a", "b"],
        "skus": [
            {"id": "s1", "name": "Staple", "category": "staple", "prices": {"a": price(a["s1"]), "b": price(prices_b["s1"])}},
            {"id": "f1", "name": "Fresh one", "category": "fresh", "prices": {"a": price(a["f1"]), "b": price(prices_b["f1"])}},
            {"id": "f2", "name": "Fresh two", "category": "fresh", "prices": {"a": price(a["f2"]), "b": price(prices_b["f2"])}},
        ],
    }


def _offer(offer_id="b_fresh_half", bank="Bank One", rate_bps=5000, min_bill=1500, cap=800, valid_to="2026-10-31", days=None):
    return {"id": offer_id, "bank": bank, "product": "credit", "store_id": "b", "days": days or ALL_DAYS, "rate_bps": rate_bps,
            "min_bill_lkr": min_bill, "cap_lkr": cap, "include_categories": ["fresh"], "exclude_categories": [],
            "valid_to": valid_to, "stackable": False}


BASKET = [{"sku_id": "s1", "qty": 1}, {"sku_id": "f1", "qty": 1}, {"sku_id": "f2", "qty": 1}]
WALLET = ["Bank One"]


def _stores(plan):
    return [b["store_id"] for b in plan["stores"]]


def test_split_beats_single_store_when_offer_pays():
    # Single a: 3000. Single b: 3100 - min(50% of 2000, 800) = 2300. Split: s1 at a 1000 + fresh at b 1200 + trip 50 = 2250.
    plan = plan_day(_catalog(), {"card_offers": [_offer()]}, BASKET, DAY, WALLET, max_stores=2, trip_cost_lkr=50, usual_store="a")
    assert plan["solver_status"] == "OPTIMAL"
    assert sorted(_stores(plan)) == ["a", "b"]
    assert plan["effective_cost_lkr"] == 2250
    assert plan["baseline_single"] == {"store_id": "b", "total_lkr": 2300, "basis": "best one-store plan with promotions and card offers"}
    assert plan["saving_vs_single_lkr"] == 50
    bill_b = next(b for b in plan["stores"] if b["store_id"] == "b")
    assert {l["sku_id"] for l in bill_b["lines"]} == {"f1", "f2"} and bill_b["card"]["bank"] == "Bank One"


def test_trip_cost_prevents_tiny_splits():
    plan = plan_day(_catalog(), {"card_offers": [_offer()]}, BASKET, DAY, WALLET, max_stores=2, trip_cost_lkr=200, usual_store="a")
    assert _stores(plan) == ["b"]
    assert plan["effective_cost_lkr"] == 2300 and plan["extra_trip_cost_lkr"] == 0


def test_wallet_gates_offers_and_one_card_per_bill():
    no_card = plan_day(_catalog(), {"card_offers": [_offer()]}, BASKET, DAY, ["Other Bank"], max_stores=2, trip_cost_lkr=50, usual_store="a")
    assert no_card["card_discount_lkr"] == 0 and _stores(no_card) == ["a"] and no_card["effective_cost_lkr"] == 3000

    two_cards = {"card_offers": [_offer(), _offer("b_fresh_other", bank="Bank Two", rate_bps=3500, cap=900)]}
    plan = plan_day(_catalog(), two_cards, BASKET, DAY, ["Bank One", "Bank Two"], max_stores=1, trip_cost_lkr=50, usual_store="a")
    bill = plan["stores"][0]
    assert bill["store_id"] == "b"
    assert bill["card"]["offer_id"] == "b_fresh_half" and bill["card_discount_lkr"] == 800  # never 800 + 700


def test_minimum_cap_and_expiry_hold_per_bill():
    offers = {"card_offers": [_offer()]}
    under_minimum = plan_day(_catalog(), offers, [{"sku_id": "f1", "qty": 1}], DAY, WALLET, max_stores=1, trip_cost_lkr=0, usual_store="b")
    assert under_minimum["card_discount_lkr"] == 0  # eligible 1000 < minimum 1500

    capped = plan_day(_catalog(), offers, [{"sku_id": "f1", "qty": 1}, {"sku_id": "f2", "qty": 1}], DAY, WALLET, max_stores=1, trip_cost_lkr=0, usual_store="b")
    assert capped["card_discount_lkr"] == 800  # 50% of 2000 = 1000, capped at 800

    expired = plan_day(_catalog(), {"card_offers": [_offer(valid_to="2026-10-23")]}, BASKET, DAY, WALLET, max_stores=1, trip_cost_lkr=0, usual_store="b")
    assert expired["card_discount_lkr"] == 0


def test_promotion_applies_before_card_offer():
    offers = {
        "card_offers": [_offer(cap=2000)],
        "store_promotions": [{"id": "b_f1_20", "store_id": "b", "sku_id": "f1", "rate_bps": 2000, "days": ALL_DAYS, "valid_to": "2026-10-31"}],
    }
    plan = plan_day(_catalog(), offers, [{"sku_id": "f1", "qty": 1}, {"sku_id": "f2", "qty": 1}], DAY, WALLET, max_stores=1, trip_cost_lkr=0, usual_store="b")
    bill = plan["stores"][0]
    f1 = next(l for l in bill["lines"] if l["sku_id"] == "f1")
    assert f1["promo_saving_lkr"] == 200 and f1["promoted_lkr"] == 800
    assert bill["card_discount_lkr"] == 900  # 50% of (800 + 1000), not of 2000
    assert bill["bill_lkr"] == 1800 - 900


def test_savings_equal_baseline_minus_plan():
    plan = plan_day(_catalog(), {"card_offers": [_offer()]}, BASKET, DAY, WALLET, max_stores=2, trip_cost_lkr=50, usual_store="a")
    assert plan["baseline_usual"]["total_lkr"] == 3000
    assert plan["saving_vs_usual_lkr"] == plan["baseline_usual"]["total_lkr"] - plan["effective_cost_lkr"] == 750
    assert plan["saving_vs_single_lkr"] == plan["baseline_single"]["total_lkr"] - plan["effective_cost_lkr"]
    assert plan["effective_cost_lkr"] == sum(b["bill_lkr"] for b in plan["stores"]) + plan["extra_trip_cost_lkr"]


def test_day_sweep_stays_before_run_out():
    # Synthetic: the offer only runs on Friday 23 Oct; a run-out on 22 Oct must not pick it.
    friday_only = {"card_offers": [_offer(days=["friday"])]}
    late = day_sweep(_catalog(), friday_only, BASKET, "2026-10-19", "2026-10-22", WALLET, 1, 0, "a")
    assert late["best"]["date"] <= "2026-10-22" and all(d["date"] <= "2026-10-22" for d in late["days"])
    early = day_sweep(_catalog(), friday_only, BASKET, "2026-10-19", "2026-10-24", WALLET, 1, 0, "a")
    assert early["best"]["date"] == "2026-10-23" and early["best"]["effective_cost_lkr"] == 2300

    # Real fixtures: due and soon items as of 18 Oct; best day never after the earliest run-out.
    catalog, offers = json.loads((V2 / "catalog.json").read_text()), json.loads((V2 / "offers.json").read_text())
    history_map = json.loads((V2 / "history-map.json").read_text())
    bills = json.loads((ROOT / "samples" / "purchase-history.json").read_text(encoding="utf-8"))["bills"]
    bills += json.loads((V2 / "history-fictional.json").read_text())["bills"]
    items = [i for i in pantry(bills, catalog, history_map, date(2026, 10, 18)) if i["status"] in ("due", "soon")]
    assert items
    lines = [{"sku_id": i["sku_id"], "qty": i["usual_qty"]} for i in items]
    deadline = min(i["next_due"] for i in items)
    sweep = day_sweep(catalog, offers, lines, "2026-10-18", deadline, ["Commercial Bank", "Nations Trust Bank", "HNB"])
    assert sweep["best"]["date"] <= max(deadline, "2026-10-18")
    assert sweep["best"] in sweep["days"]


def test_rejects_impossible_inputs():
    import pytest

    args = (_catalog(), {"card_offers": [_offer()]})
    for bad_lines in ([{"sku_id": "s1", "qty": -5}], [{"sku_id": "s1", "qty": 0}], [{"sku_id": "s1", "qty": 1000}],
                      [{"sku_id": "s1", "qty": True}], [{"sku_id": None, "qty": 1}]):
        with pytest.raises(ValueError):
            plan_day(*args, bad_lines, DAY, WALLET, max_stores=2, trip_cost_lkr=50, usual_store="a")
    for bad_trip in (-500, 10**6, 2.5):
        with pytest.raises(ValueError):
            plan_day(*args, BASKET, DAY, WALLET, max_stores=2, trip_cost_lkr=bad_trip, usual_store="a")
    with pytest.raises(ValueError):
        plan_day(*args, BASKET, DAY, WALLET, max_stores=3, trip_cost_lkr=50, usual_store="a")


def test_plans_are_deterministic_with_tie_breaks():
    args = (_catalog(), {"card_offers": [_offer()]}, BASKET, DAY, WALLET)
    assert plan_day(*args, max_stores=2, trip_cost_lkr=50, usual_store="a") == plan_day(*args, max_stores=2, trip_cost_lkr=50, usual_store="a")

    same_prices = _catalog({"s1": 1000, "f1": 1000, "f2": 1000})
    to_a = plan_day(same_prices, {}, BASKET, DAY, [], max_stores=2, trip_cost_lkr=0, usual_store="a")
    to_b = plan_day(same_prices, {}, BASKET, DAY, [], max_stores=2, trip_cost_lkr=0, usual_store="b")
    assert _stores(to_a) == ["a"] and _stores(to_b) == ["b"]  # fewer stores first, then the usual store
