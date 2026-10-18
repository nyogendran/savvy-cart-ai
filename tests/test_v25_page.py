"""v2.5: tighter pantry rows, half-kilo steps, bill tables with unit prices, consolidated demo wording (SC-030)."""

from __future__ import annotations

import html
import re
from pathlib import Path

from fastapi.testclient import TestClient

from savvycart.http import V2_BANNER, _half_kilos, _v2_catalog, app

from test_v21_page import _submit
from test_v24_page import _last, _text

ROOT = Path(__file__).resolve().parents[1]


def _bills(page: str) -> dict[str, str]:
    return dict(re.findall(r'<article class="bill" data-store="(\w+)">(.*?)</article>', page, re.S))


def test_pantry_summary_sits_under_the_item_name():
    assert _last(".item details.reason summary", "min-height") == "28px"
    assert _last(".item details.reason summary", "padding") == "0"
    assert _last("details summary", "min-height") == "44px"  # every other summary keeps the 44px target
    # The 44px quantity input spans both rows, so the first row is only as tall as the item name.
    assert _last(".item .qty", "grid-row") == "1 / span 2" and _last(".item .reason", "grid-row") == "2"
    # Bills may shrink below their tables' minimum width, so tables scroll inside the card on phones.
    assert _last(".bills", "grid-template-columns") == "minmax(0, 1fr)"


def test_add_item_quantity_matches_the_row_quantities():
    with TestClient(app) as http:
        home = http.get("/").text
    assert '<input type="number" id="add_qty" name="add_qty" min="0.5" max="50" step="0.5" value="1">' in home
    assert _last("#add_qty", "text-align") == "right" and _last("#add_qty", "width") == "5em"
    assert _last('.item input[type="number"]', "width") == "5em" and _last('.item input[type="number"]', "text-align") == "right"


def test_weighed_items_snap_to_half_kilos():
    assert [_half_kilos(kg) for kg in (0.2, 0.74, 0.75, 1.034, 1.26, 1.5)] == [0.5, 0.5, 1.0, 1.0, 1.5, 1.5]
    with TestClient(app) as http:
        home = http.get("/").text
        planned = {kg: _submit(http, home, "plan", [("qty_carrot", kg)]) for kg in ("0.2", "0.74", "0.75", "1.26")}
    weighed = re.findall(r'<label class="sr-only" for="qty_(\w+)">Quantity of [^<]* in kg</label><input type="number"[^>]*>', home)
    assert weighed and "banana_ambul" in weighed
    for sku in weighed:
        attrs = re.search(rf'<input type="number" id="qty_{sku}" [^>]*>', home).group(0)
        assert 'min="0.5"' in attrs and 'step="0.5"' in attrs, attrs
        assert float(re.search(r'value="([^"]+)"', attrs).group(1)) % 0.5 == 0, attrs
    assert 'id="qty_banana_ambul" name="qty_banana_ambul" min="0.5" max="50" step="0.5" value="1"' in home
    assert re.search(r'id="qty_tea_bun" [^>]*step="1"[^>]*value="\d+"', home)  # packs stay whole
    for typed, expected in {"0.2": "0.5", "0.74": "0.5", "0.75": "1", "1.26": "1.5"}.items():
        carrot = re.search(r"<tr><td>Carrot</td><td class=\"num\">([^<]+)</td>", planned[typed]).group(1)
        assert carrot == f"{expected} kg", (typed, carrot)


def test_default_plan_figures_after_half_kilo_steps():
    with TestClient(app) as http:
        home = http.get("/").text
        plan = _submit(http, home, "plan")
        why = _submit(http, plan, "explain")
    assert "LKR 4,604" in plan and "LKR 1,328" in plan and "LKR 4,609" not in plan
    assert "Plan total 4604 LKR, saving 1328 LKR against your usual store at shelf price." in _text(why)


def test_bill_tables_show_unit_prices_and_one_price_source_line():
    skus = {s["id"]: s for s in _v2_catalog()["skus"]}
    names = {s["name"]: s for s in skus.values()}
    with TestClient(app) as http:
        plan = _submit(http, http.get("/").text, "plan")
    assert '<div class="bills">' in plan and '<div class="grid two"><article class="bill"' not in plan
    bills = _bills(plan)
    assert set(bills) == {"keells", "cargills"}
    for store, block in bills.items():
        header = re.findall(r"<th[^>]*>([^<]+)</th>", block)
        assert header == ["Item", "Qty", "Unit price (LKR)", "Shelf (LKR)", "Promotion (LKR)"]
        body = re.search(r"<tbody>(.*?)</tbody>", block, re.S).group(1)
        assert "LKR" not in body and "(receipt price)" not in body and "(fictional price)" not in body and "*" not in body
        for name, qty, unit_price, shelf, promo in re.findall(
                r'<tr><td>([^<]+)</td><td class="num">([^<]+)</td><td class="num">([^<]+)</td>'
                r'<td class="num">([^<]+)</td><td class="num">([^<]+)</td></tr>', body):
            sku = names[html.unescape(name)]
            assert qty.endswith(" kg") == (sku.get("unit") == "kg"), (name, qty)
            assert int(unit_price.replace(",", "")) == sku["prices"][store]["amount_lkr"], name
            assert re.fullmatch(r"[\d,]+", shelf) and (promo == "-" or re.fullmatch(r"[\d,]+", promo)), (shelf, promo)
        footer = re.search(r"<tfoot>(.*?)</tfoot>", block, re.S).group(1)
        assert re.search(r'Card discount</td><td class="num">LKR [\d,]+<', footer)
        assert re.search(r'Bill total</td><td class="num">LKR [\d,]+<', footer)
    assert bills["keells"].count('<p class="source">Prices from Keells receipts.</p>') == 1
    assert bills["cargills"].count('<p class="source">Fictional demo prices.</p>') == 1
    assert ".00" not in re.sub(r"<[^>]+>", " ", "".join(bills.values()))


def test_bill_marks_fictional_rows_when_sources_are_mixed():
    from savvycart.http import _render_bill

    bill = {"store_id": "keells", "card": None, "card_discount_lkr": 0, "bill_lkr": 900,
            "lines": [{"sku_id": "carrot", "name": "Carrot", "qty": 0.5, "shelf_lkr": 95, "promo_saving_lkr": 0, "price_source": "receipt"},
                      {"sku_id": "tea_bun", "name": "Tea bun, 2 pack", "qty": 2, "shelf_lkr": 368, "promo_saving_lkr": 0,
                       "price_source": "fictional"}]}
    block = _render_bill(bill)
    assert "<td>Carrot</td>" in block and "<td>Tea bun, 2 pack *</td>" in block
    assert block.count('<p class="source">Prices from receipts except those marked * (fictional).</p>') == 1


def test_demo_wording_is_consolidated():
    with TestClient(app) as http:
        home = http.get("/").text
        plan = _submit(http, home, "plan")
    for page in (home, plan):
        assert "Pretend" not in page and "demo control" not in page
        details = re.search(r'<div class="banner" id="banner">.*?<details>(.*?)</details>', page, re.S).group(1)
        assert html.escape(V2_BANNER, quote=True) in details
        assert "<p>The planning date runs from 17 to 31 Oct 2026 because the sample purchase history ends on 17 Oct 2026.</p>" in details
    assert '<label for="today">Planning date (17 to 31 Oct 2026)</label>' in home


def test_readme_describes_v25():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in ("How this was calculated", "Due in 3 days", "Karuppan's household", "Shop on Friday 23 Oct at Keells and Cargills",
                   "LKR 4,604", "LKR 1,328", "Planning date", "half kilos"):
        assert phrase in readme, phrase
    for stale in ("LKR 4,609", "LKR 1,331", "Pretend today is", "lists every tool it called"):
        assert stale not in readme, stale
