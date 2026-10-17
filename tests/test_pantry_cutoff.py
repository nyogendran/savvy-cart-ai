"""The pantry never sees purchases made after the planning date (SC-019 AC1)."""

from __future__ import annotations

from datetime import date

from savvycart.pantry import pantry

CATALOG = {"stores": ["keells"], "skus": [{"id": "milk", "name": "Milk", "category": "staple", "prices": {}}]}
HISTORY_MAP = {"MILK": "milk"}


def _bill(day: str) -> dict:
    return {"date": day, "chain": "keells", "source": "fictional", "lines": [{"line": 1, "raw": "MILK", "qty": 1.0, "unit_lkr": 100, "amount_lkr": 100}],
            "promotions": [], "card_offers": [], "gross_lkr": 100, "net_lkr": 100}


def test_bills_after_planning_date_are_ignored():
    bills = [_bill(d) for d in ("2026-10-01", "2026-10-08", "2026-10-15", "2026-10-22", "2026-10-29")]
    (before,) = pantry(bills, CATALOG, HISTORY_MAP, date(2026, 10, 16))
    assert before["purchase_dates"] == 3 and before["last_bought"] == "2026-10-15"
    assert before["next_due"] == "2026-10-22" and before["days_left"] == 6
    (on_the_day,) = pantry(bills, CATALOG, HISTORY_MAP, date(2026, 10, 22))
    assert on_the_day["purchase_dates"] == 4 and on_the_day["last_bought"] == "2026-10-22"
    (too_early,) = pantry(bills, CATALOG, HISTORY_MAP, date(2026, 10, 5))
    assert too_early["status"] == "unknown" and too_early["purchase_dates"] == 1
