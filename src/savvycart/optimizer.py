"""Deterministic one-store basket optimizer (integer LKR)."""

from __future__ import annotations

from typing import Any


def _sku_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {sku["id"]: sku for sku in catalog["skus"]}


def _store_ids(catalog: dict[str, Any]) -> list[str]:
    stores: set[str] = set()
    for sku in catalog["skus"]:
        stores.update(sku.get("prices", {}).keys())
    return sorted(stores)


def _offers_for_store(offers: list[dict[str, Any]], store_id: str) -> list[dict[str, Any]]:
    return [offer for offer in offers if offer.get("store_id") == store_id]


def _pick_offer(
    offers: list[dict[str, Any]],
    store_id: str,
    weekday: str,
) -> dict[str, Any] | None:
    """At most one offer per store-day in the demo fixtures."""
    matches = [
        offer
        for offer in _offers_for_store(offers, store_id)
        if weekday in offer.get("days", []) and offer.get("channel") == "in_store"
    ]
    return matches[0] if matches else None


def _line_shelf(
    sku: dict[str, Any] | None,
    qty: int,
    store_id: str,
) -> tuple[int | None, str]:
    if sku is None:
        return None, "unpriced"
    price = sku.get("prices", {}).get(store_id)
    if not price or "amount_lkr" not in price:
        return None, "unpriced"
    return int(price["amount_lkr"]) * int(qty), "priced"


def _line_bucket(
    *,
    status: str,
    sku: dict[str, Any] | None,
    offer: dict[str, Any] | None,
    store_id: str,
    weekday: str,
    date: str,
) -> str:
    if status == "unpriced":
        return "unpriced"
    if offer is None:
        return "excluded"
    if date > offer["valid_to"]:
        return "excluded"
    if weekday not in offer.get("days", []):
        return "excluded"
    if offer.get("store_id") != store_id:
        return "excluded"
    if offer.get("channel") != "in_store":
        return "excluded"
    category = sku["category"]
    include = offer.get("include_categories") or []
    exclude = offer.get("exclude_categories") or []
    if category in include and category not in exclude:
        return "eligible"
    return "excluded"


def _plan_for_store(
    *,
    catalog: dict[str, Any],
    offers: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    day: dict[str, str],
    store_id: str,
) -> dict[str, Any]:
    skus = _sku_map(catalog)
    weekday = day["weekday"]
    date = day["date"]
    offer = _pick_offer(offers, store_id, weekday)

    line_rows: list[dict[str, Any]] = []
    shelf_total = 0
    eligible_subtotal = 0
    complete = True

    for line in lines:
        sku_id = line["sku_id"]
        qty = int(line["qty"])
        sku = skus.get(sku_id)
        shelf, price_status = _line_shelf(sku, qty, store_id)
        bucket = _line_bucket(
            status=price_status,
            sku=sku,
            offer=offer,
            store_id=store_id,
            weekday=weekday,
            date=date,
        )
        if bucket == "unpriced":
            complete = False
            line_rows.append(
                {
                    "sku_id": sku_id,
                    "qty": qty,
                    "status": "unpriced",
                    "shelf_lkr": None,
                }
            )
            continue
        assert shelf is not None
        shelf_total += shelf
        if bucket == "eligible":
            eligible_subtotal += shelf
        line_rows.append(
            {
                "sku_id": sku_id,
                "qty": qty,
                "status": bucket,
                "shelf_lkr": shelf,
            }
        )

    reason: str | None = None
    discount = 0
    rate_bps = int(offer["rate_bps"]) if offer is not None else 0
    naive_discount = (shelf_total * rate_bps) // 10000 if offer is not None else 0

    if offer is not None and date > offer["valid_to"]:
        discount = 0
        reason = "expired"
    elif offer is None:
        discount = 0
    elif eligible_subtotal < int(offer["min_bill_lkr"]):
        discount = 0
    else:
        raw = (eligible_subtotal * rate_bps) // 10000
        discount = min(raw, int(offer["cap_lkr"]))

    deferred_value = 0
    effective_cost = shelf_total - discount

    return {
        "store_id": store_id,
        "complete": complete,
        "shelf_total": shelf_total,
        "eligible_subtotal": eligible_subtotal,
        "discount": discount,
        "naive_discount": naive_discount,
        "deferred_value": deferred_value,
        "effective_cost": effective_cost,
        "reason": reason,
        "offer_id": offer["id"] if offer is not None else None,
        "lines": line_rows,
    }


def optimize(
    catalog: dict[str, Any],
    offers: list[dict[str, Any]] | dict[str, Any],
    lines: list[dict[str, Any]],
    day: dict[str, str],
    usual_store: str,
) -> dict[str, Any]:
    """Return one-store plans and the winning complete plan.

    ``offers`` may be a list or an ``{"offers": [...]}`` document.
    Line ``raw`` / instruction fields are ignored.
    """
    offer_list = offers["offers"] if isinstance(offers, dict) else offers
    # Normalize to sku_id + qty only (ignore raw / confidence / instruction text).
    # Lines without a sku_id (e.g. injection-only OCR rows) do not enter the basket.
    clean_lines = [
        {"sku_id": line["sku_id"], "qty": int(line["qty"])}
        for line in lines
        if line.get("sku_id")
    ]

    plans = [
        _plan_for_store(
            catalog=catalog,
            offers=offer_list,
            lines=clean_lines,
            day=day,
            store_id=store_id,
        )
        for store_id in _store_ids(catalog)
    ]

    complete_plans = [plan for plan in plans if plan["complete"]]
    winner = None
    if complete_plans:
        best_cost = min(plan["effective_cost"] for plan in complete_plans)
        tied = [plan for plan in complete_plans if plan["effective_cost"] == best_cost]
        winner = next((plan for plan in tied if plan["store_id"] == usual_store), tied[0])

    return {
        "day": {"weekday": day["weekday"], "date": day["date"]},
        "usual_store": usual_store,
        "plans": plans,
        "winner": winner,
    }
