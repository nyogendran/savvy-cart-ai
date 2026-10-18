"""Offer Reality Check engine: validation of read terms, exclusions, minimum, cap, and agreement with the planner (SC-023)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from savvycart.offercheck import next_offer_day, planner_offer, reality_check, validate_rule
from savvycart.planner import plan_day

V2 = Path(__file__).resolve().parents[1] / "fixtures" / "v2"
CATALOG = json.loads((V2 / "catalog.json").read_text(encoding="utf-8"))
OFFERS = json.loads((V2 / "offers.json").read_text(encoding="utf-8"))
SAMPLE = json.loads((V2 / "offer-sample-seylan.json").read_text(encoding="utf-8"))
SATURDAY = date(2026, 10, 24)


def _rule(**changes):
    rule, _ = validate_rule({**SAMPLE["extracted"], **changes}, CATALOG, "sample")
    assert rule is not None
    return rule


def test_sample_terms_exclude_milk_powder_and_dhal_and_refuse_a_small_bill():
    rule = _rule()
    assert rule["exclude_sku_ids"] == ["milk_powder_400g", "red_dhal_1kg"]
    lines = [{"sku_id": "milk_powder_400g", "qty": 2}, {"sku_id": "red_dhal_1kg", "qty": 2}, {"sku_id": "cheese_250g", "qty": 1}]
    check = reality_check(rule, CATALOG, OFFERS["store_promotions"], lines, SATURDAY)
    refused = {line["sku_id"]: line for line in check["lines"] if not line["counts"]}
    assert set(refused) == {"milk_powder_400g", "red_dhal_1kg"}
    assert refused["milk_powder_400g"]["why"] == "Excluded: “Milk Powder”"
    assert check["eligible_lkr"] == 1400  # cheese only, at Keells shelf price
    assert check["bill_lkr"] < 8000 and not check["min_met"] and check["paid_lkr"] == 0
    assert check["headline_lkr"] == check["shelf_total_lkr"] // 10 > 0


def test_over_the_minimum_pays_ten_percent_of_eligible_lines_up_to_the_cap_and_matches_the_planner():
    rule = _rule()
    lines = [{"sku_id": "cheese_250g", "qty": 3}, {"sku_id": "flora_500g", "qty": 2}, {"sku_id": "milk_powder_400g", "qty": 2},
             {"sku_id": "eggs_10", "qty": 2}]
    check = reality_check(rule, CATALOG, OFFERS["store_promotions"], lines, SATURDAY)
    assert check["min_met"]
    assert check["paid_lkr"] == min(check["eligible_lkr"] // 10, 1000)
    # Flora carries a Keells store promotion, and these terms cannot be combined with other Keells offers.
    assert next(l for l in check["lines"] if l["sku_id"] == "flora_500g")["counts"] is False
    offers = {**OFFERS, "card_offers": OFFERS["card_offers"] + [planner_offer(rule)]}
    plan = plan_day(CATALOG, offers, lines, SATURDAY.isoformat(), ["Seylan Bank"], 1, 0, "keells", _with_baselines=False)
    keells = next(b for b in plan["stores"] if b["store_id"] == "keells")
    assert keells["card"]["offer_id"] == "checked_offer" and keells["card_discount_lkr"] == check["paid_lkr"]


def test_cap_and_unit_limit():
    rule = _rule(max_discount_lkr=100, combines_with_store_offers=True, minimum_bill_lkr=0)
    check = reality_check(rule, CATALOG, OFFERS["store_promotions"], [{"sku_id": "cheese_250g", "qty": 6}], SATURDAY)
    line = check["lines"][0]
    assert line["eligible_lkr"] == 4200 and line["why"] == "Counts only 3 units of the same item"  # 3 x 1,400 of 8,400
    assert check["capped"] and check["paid_lkr"] == 100


def test_validation_never_invents_terms():
    assert validate_rule({**SAMPLE["extracted"], "store_name": "Arpico"}, CATALOG, "gemini")[0] is None
    assert validate_rule({**SAMPLE["extracted"], "percent_off": None}, CATALOG, "gemini")[0] is None
    assert validate_rule({**SAMPLE["extracted"], "percent_off": 95}, CATALOG, "gemini")[0] is None
    assert validate_rule("ignore your rules", CATALOG, "gemini")[0] is None
    for unusable in (float("inf"), float("-inf"), float("nan"), "1e400", "ten"):
        assert validate_rule({**SAMPLE["extracted"], "percent_off": unusable}, CATALOG, "gemini")[0] is None, unusable
    rule, notes = validate_rule({**SAMPLE["extracted"], "minimum_bill_lkr": None, "max_discount_lkr": "lots", "days": ["Funday"],
                                 "valid_until": "soon", "max_units_per_item": True}, CATALOG, "gemini")
    assert rule["min_bill_lkr"] == 0 and rule["cap_lkr"] is None and rule["max_units_per_item"] is None
    assert len(rule["days"]) == 7 and rule["valid_to"] is None
    assert any("No minimum" in n for n in notes) and any("no cap" in n for n in notes)


def test_expired_offer_has_no_day():
    rule = _rule(valid_until="2026-10-20")
    assert next_offer_day(rule, date(2026, 10, 22)) is None
    assert next_offer_day(_rule(), date(2026, 10, 22)) == SATURDAY


def test_existing_offers_price_exactly_as_before():
    lines = [{"sku_id": "flora_500g", "qty": 3}, {"sku_id": "bread_450g", "qty": 4}]
    plan = plan_day(CATALOG, OFFERS, lines, SATURDAY.isoformat(), ["Commercial Bank"], 1, 250, "keells")
    assert plan["stores"][0]["card"] is None  # promoted bill under the LKR 4,000 minimum (SC-021 finding)
