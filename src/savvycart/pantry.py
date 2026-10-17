"""Pantry: when each regular item runs low, from purchase dates alone (no model)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

DUE_DAYS = 3
SOON_DAYS = 7
MIN_DATES_FOR_DUE = 3


def _round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def purchases_by_sku(bills: list[dict[str, Any]], history_map: dict[str, str]) -> dict[str, dict[date, float]]:
    """Total quantity bought per SKU per distinct date; unmapped lines are ignored."""
    bought: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for bill in bills:
        day = date.fromisoformat(bill["date"])
        for line in bill["lines"]:
            sku_id = history_map.get(line["raw"])
            if sku_id:
                bought[sku_id][day] += float(line["qty"])
    return bought


def pantry(
    bills: list[dict[str, Any]],
    catalog: dict[str, Any],
    history_map: dict[str, str],
    today: date,
) -> list[dict[str, Any]]:
    """One entry per catalog SKU, ordered by days left (unknown last)."""
    names = {sku["id"]: sku["name"] for sku in catalog["skus"]}
    bought = purchases_by_sku([b for b in bills if b["date"] <= today.isoformat()], history_map)
    items = []
    for sku_id, name in names.items():
        dates = sorted(bought.get(sku_id, {}))
        if len(dates) < 2:
            items.append(
                {
                    "sku_id": sku_id,
                    "name": name,
                    "purchase_dates": len(dates),
                    "status": "unknown",
                    "reason": f"Bought on {len(dates)} day{'s' if len(dates) != 1 else ''}; not enough history to estimate.",
                }
            )
            continue
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        cadence = _round_half_up(statistics.median(gaps))
        usual_qty = round(statistics.median(bought[sku_id][d] for d in dates), 3)
        last = dates[-1]
        next_due = last + timedelta(days=cadence)
        days_left = (next_due - today).days
        if days_left <= DUE_DAYS and len(dates) >= MIN_DATES_FOR_DUE:
            status = "due"
        elif days_left <= SOON_DAYS:
            status = "soon"
        else:
            status = "ok"
        items.append(
            {
                "sku_id": sku_id,
                "name": name,
                "purchase_dates": len(dates),
                "cadence_days": cadence,
                "usual_qty": usual_qty,
                "last_bought": last.isoformat(),
                "next_due": next_due.isoformat(),
                "days_left": days_left,
                "status": status,
                "reason": (
                    f"Bought on {len(dates)} days, usually every {cadence} days; "
                    f"last on {last.isoformat()}, so next due {next_due.isoformat()} ({days_left} days from {today.isoformat()})."
                ),
            }
        )
    order = {"due": 0, "soon": 1, "ok": 2, "unknown": 3}
    return sorted(items, key=lambda i: (order[i["status"]], i.get("days_left", 10**6), i["sku_id"]))
