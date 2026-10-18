"""Exact day planner: split a basket across up to four stores, one card per bill (OR-Tools CP-SAT)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ortools.sat.python import cp_model

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
# Objective = cost * COST_SCALE + tie-break score; the tie-break score stays far below COST_SCALE.
COST_SCALE = 1000
MAX_QTY = 50
MAX_TRIP_COST_LKR = 5000
MAX_STORES = 4


def _lkr(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _applies(rule: dict[str, Any], store_id: str, day: date) -> bool:
    return (
        rule["store_id"] == store_id
        and WEEKDAYS[day.weekday()] in rule["days"]
        and day <= date.fromisoformat(rule["valid_to"])
    )


def _eligible(offer: dict[str, Any], category: str) -> bool:
    include = offer.get("include_categories") or []
    exclude = offer.get("exclude_categories") or []
    return (not include or category in include) and category not in exclude


def card_base(offer: dict[str, Any], sku: dict[str, Any], promoted: int, has_promo: bool, qty: float) -> int:
    """LKR of one line that a card offer's rate applies to; 0 when the offer's terms refuse the line."""
    if not _eligible(offer, sku["category"]) or sku["id"] in (offer.get("exclude_sku_ids") or []):
        return 0
    if has_promo and offer.get("stacks_with_promotions") is False:
        return 0
    limit = offer.get("max_units_per_item")
    if limit and qty > limit:
        return _lkr(promoted * limit / qty)
    return promoted


def _promotion_saving(promotion: dict, shelf: int, unit_lkr: float, qty: float) -> int:
    """Integer LKR a promotion takes off one line: a percent, or a fixed unit price for up to max_qty units."""
    if promotion.get("type") == "fixed_price":
        units = min(qty, promotion["max_qty"])
        return max(_lkr(unit_lkr * units) - _lkr(promotion["price_lkr"] * units), 0)
    return (shelf * promotion["rate_bps"]) // 10000


def _best_promotion(promotions: list[dict], sku: dict, store_id: str, day: date, shelf: int, unit_lkr: float, qty: float) -> tuple[dict | None, int]:
    """Promotions do not stack: the single one that saves most on this line at this store."""
    matching = [
        p for p in promotions
        if _applies(p, store_id, day)
        and (p.get("sku_id") == sku["id"] or (p.get("type") != "fixed_price" and p.get("category") == sku["category"]))
    ]
    scored = [(_promotion_saving(p, shelf, unit_lkr, qty), p["id"], p) for p in matching]
    best = max(scored, key=lambda s: (s[0], s[1]), default=None)
    return (best[2], best[0]) if best and best[0] > 0 else (None, 0)


def _wallet_banks(wallet: list[Any]) -> set[str]:
    return {card["bank"] if isinstance(card, dict) else str(card) for card in wallet}


def plan_day(
    catalog: dict[str, Any],
    offers: dict[str, Any],
    lines: list[dict[str, Any]],
    day: str,
    wallet: list[Any],
    max_stores: int = 2,
    trip_cost_lkr: int = 250,
    usual_store: str = "keells",
    *,
    _with_baselines: bool = True,
) -> dict[str, Any]:
    """Cheapest legal plan for the confirmed lines on one day."""
    if isinstance(max_stores, bool) or max_stores not in range(1, MAX_STORES + 1):
        raise ValueError(f"max_stores must be from 1 to {MAX_STORES}")
    if not isinstance(trip_cost_lkr, int) or not 0 <= trip_cost_lkr <= MAX_TRIP_COST_LKR:
        raise ValueError(f"trip_cost_lkr must be an integer from 0 to {MAX_TRIP_COST_LKR}")
    for line in lines:
        qty = line.get("qty")
        if not isinstance(line.get("sku_id"), str) or isinstance(qty, bool) or not isinstance(qty, (int, float)) or not 0 < qty <= MAX_QTY:
            raise ValueError(f"each line needs a sku_id and a quantity above 0 and at most {MAX_QTY}")
    the_day = date.fromisoformat(day)
    stores: list[str] = list(catalog["stores"])
    rank = {store: (0 if store == usual_store else 1 + i) for i, store in enumerate(stores)}
    skus = {sku["id"]: sku for sku in catalog["skus"]}
    banks = _wallet_banks(wallet)
    card_offers = [o for o in offers.get("card_offers", []) if o["bank"] in banks]
    promotions = offers.get("store_promotions", [])

    # Per line and store: shelf amount, best promotion, promoted amount (integer LKR).
    cells: dict[tuple[int, str], dict[str, Any]] = {}
    unpriced = []
    for i, line in enumerate(lines):
        sku = skus.get(line["sku_id"])
        priced = False
        for store in stores:
            price = (sku or {}).get("prices", {}).get(store)
            if not price:
                continue
            shelf = _lkr(price["amount_lkr"] * float(line["qty"]))
            promo, saving = _best_promotion(promotions, sku, store, the_day, shelf, price["amount_lkr"], float(line["qty"]))
            cells[(i, store)] = {"shelf": shelf, "promoted": shelf - saving, "promo": promo, "promo_saving": saving}
            priced = True
        if not priced:
            unpriced.append(line["sku_id"])
    priced_lines = [i for i in range(len(lines)) if any((i, s) in cells for s in stores)]

    model = cp_model.CpModel()
    x = {key: model.NewBoolVar(f"x_{key[0]}_{key[1]}") for key in cells}
    used = {s: model.NewBoolVar(f"used_{s}") for s in stores}
    for i in priced_lines:
        model.AddExactlyOne(x[(i, s)] for s in stores if (i, s) in x)
    for (i, s), var in x.items():
        model.AddImplication(var, used[s])
    for s in stores:
        model.Add(used[s] <= sum(var for (i, st), var in x.items() if st == s))
    model.Add(sum(used.values()) <= max_stores)

    active = {s: [o for o in card_offers if _applies(o, s, the_day)] for s in stores}
    pick, discount = {}, {}
    for s in stores:
        for o in active[s]:
            key = (s, o["id"])
            pick[key] = model.NewBoolVar(f"pick_{s}_{o['id']}")
            discount[key] = model.NewIntVar(0, int(o["cap_lkr"]), f"disc_{s}_{o['id']}")
            at_store = [i for i in priced_lines if (i, s) in x]
            eligible = sum(
                card_base(o, skus[lines[i]["sku_id"]], cells[(i, s)]["promoted"], cells[(i, s)]["promo"] is not None,
                          float(lines[i]["qty"])) * x[(i, s)]
                for i in at_store
            )
            minimum_base = sum(cells[(i, s)]["promoted"] * x[(i, s)] for i in at_store) if o.get("minimum_basis") == "bill" else eligible
            model.Add(minimum_base >= int(o["min_bill_lkr"])).OnlyEnforceIf(pick[key])
            model.Add(discount[key] <= int(o["cap_lkr"]) * pick[key])
            model.Add(10000 * discount[key] <= int(o["rate_bps"]) * eligible)
        if active[s]:
            model.Add(sum(pick[(s, o["id"])] for o in active[s]) <= used[s])

    promoted_total = sum(cells[key]["promoted"] * var for key, var in x.items())
    stores_used = sum(used.values())
    cost = promoted_total - sum(discount.values()) + trip_cost_lkr * stores_used
    tie_break = 100 * stores_used + sum(rank[s] * used[s] for s in stores)
    model.Minimize(COST_SCALE * cost + tie_break)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 7
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"planner found no plan: {status_name}")

    bills = []
    for s in stores:
        if not solver.Value(used[s]):
            continue
        bill_lines = []
        for i in priced_lines:
            if (i, s) in x and solver.Value(x[(i, s)]):
                cell, sku = cells[(i, s)], skus[lines[i]["sku_id"]]
                bill_lines.append(
                    {
                        "sku_id": sku["id"], "name": sku["name"], "category": sku["category"], "qty": lines[i]["qty"],
                        "shelf_lkr": cell["shelf"], "promoted_lkr": cell["promoted"], "promo_saving_lkr": cell["promo_saving"],
                        "promo_id": cell["promo"]["id"] if cell["promo"] else None,
                        "price_source": skus[sku["id"]]["prices"][s]["source"],
                    }
                )
        chosen = next((o for o in active[s] if solver.Value(pick[(s, o["id"])])), None)
        card_discount = solver.Value(discount[(s, chosen["id"])]) if chosen else 0
        promoted = sum(l["promoted_lkr"] for l in bill_lines)
        bills.append(
            {
                "store_id": s,
                "lines": bill_lines,
                "card": {"offer_id": chosen["id"], "bank": chosen["bank"], "product": chosen["product"]} if chosen else None,
                "shelf_lkr": sum(l["shelf_lkr"] for l in bill_lines),
                "promo_saving_lkr": sum(l["promo_saving_lkr"] for l in bill_lines),
                "card_discount_lkr": card_discount,
                "bill_lkr": promoted - card_discount,
            }
        )

    extra_trips = max(len(bills) - 1, 0)
    plan: dict[str, Any] = {
        "day": {"date": the_day.isoformat(), "weekday": WEEKDAYS[the_day.weekday()]},
        "solver_status": status_name,
        "complete": not unpriced,
        "unpriced": unpriced,
        "max_stores": max_stores,
        "trip_cost_lkr": trip_cost_lkr,
        "stores": bills,
        "shelf_total_lkr": sum(b["shelf_lkr"] for b in bills),
        "promo_saving_lkr": sum(b["promo_saving_lkr"] for b in bills),
        "card_discount_lkr": sum(b["card_discount_lkr"] for b in bills),
        "extra_trip_cost_lkr": trip_cost_lkr * extra_trips,
    }
    plan["effective_cost_lkr"] = sum(b["bill_lkr"] for b in bills) + plan["extra_trip_cost_lkr"]

    if _with_baselines:
        usual_total = sum(cells[(i, usual_store)]["shelf"] for i in priced_lines if (i, usual_store) in cells)
        usual_missing = [lines[i]["sku_id"] for i in priced_lines if (i, usual_store) not in cells]
        plan["baseline_usual"] = {"store_id": usual_store, "total_lkr": usual_total, "missing": usual_missing,
                                  "basis": "usual store shelf prices, no promotions, no card offer"}
        single = plan if max_stores == 1 else plan_day(catalog, offers, lines, day, wallet, 1, trip_cost_lkr, usual_store, _with_baselines=False)
        plan["baseline_single"] = {"store_id": single["stores"][0]["store_id"] if single["stores"] else None,
                                   "total_lkr": single["effective_cost_lkr"], "basis": "best one-store plan with promotions and card offers"}
        plan["saving_vs_usual_lkr"] = usual_total - plan["effective_cost_lkr"]
        plan["saving_vs_single_lkr"] = plan["baseline_single"]["total_lkr"] - plan["effective_cost_lkr"]
    return plan


def day_sweep(
    catalog: dict[str, Any],
    offers: dict[str, Any],
    lines: list[dict[str, Any]],
    start: str,
    deadline: str | None,
    wallet: list[Any],
    max_stores: int = 2,
    trip_cost_lkr: int = 250,
    usual_store: str = "keells",
) -> dict[str, Any]:
    """Plan each of the next seven days that fall on or before the deadline; report the cheapest."""
    first = date.fromisoformat(start)
    last = first + timedelta(days=6)
    if deadline:
        last = min(last, max(first, date.fromisoformat(deadline)))
    days = []
    current = first
    while current <= last:
        plan = plan_day(catalog, offers, lines, current.isoformat(), wallet, max_stores, trip_cost_lkr, usual_store, _with_baselines=False)
        days.append({"date": current.isoformat(), "weekday": plan["day"]["weekday"], "effective_cost_lkr": plan["effective_cost_lkr"],
                     "stores": [b["store_id"] for b in plan["stores"]]})
        current += timedelta(days=1)
    best = min(days, key=lambda d: (d["effective_cost_lkr"], d["date"]))
    return {"window_start": first.isoformat(), "window_end": last.isoformat(), "deadline": deadline, "days": days, "best": best}
