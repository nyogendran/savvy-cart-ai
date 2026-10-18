"""v2.5: tighter pantry rows, half-kilo steps, bill tables with unit prices, consolidated demo wording (SC-030)."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from savvycart.http import V2_BANNER, _half_kilos, _v2_catalog, app

from test_v21_page import _submit
from test_v24_page import _last, _text

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_explanation_budget():
    """These tests run many scripted explanations; leave the process-wide per-minute cap as later tests expect it."""
    app.state.model_rate_limiter = None
    yield
    app.state.model_rate_limiter = None


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
    halves = (0.2, 0.25, 0.74, 0.75, 1.034, 1.25, 1.26, 1.5, 2.75)
    assert [_half_kilos(kg) for kg in halves] == [0.5, 0.5, 0.5, 1.0, 1.0, 1.5, 1.5, 1.5, 3.0]  # ties round up, not to even
    with TestClient(app) as http:
        home = http.get("/").text
        planned = {kg: _submit(http, home, "plan", [("qty_carrot", kg)]) for kg in ("0.2", "0.74", "0.75", "1.26")}
        buns = _submit(http, home, "pantry", [("qty_tea_bun", "2.5")])
    assert re.search(r'id="qty_tea_bun" [^>]*step="1" value="3"', buns)  # a typed half pack is rounded up to a whole pack
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
        rows = re.findall(r'<tr><td>([^<]+)</td><td class="num">([^<]+)</td><td class="num">([^<]+)</td>'
                          r'<td class="num">([^<]+)</td><td class="num">([^<]+)</td></tr>', body)
        assert rows and len(rows) == body.count("<tr>")  # every row is checked, none skipped by a markup change
        for name, qty, unit_price, shelf, promo in rows:
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


def test_a_refused_replan_is_disclosed_as_refused():
    # The agent's pantry tool still reports 3-decimal medians; a plan_day call copying them is refused by the
    # guardrail, so the page says the attempt was refused rather than that a re-plan happened.
    async def copies_pantry_quantities(question, context):
        lines = [dict(line, qty=1.034 if line["sku_id"] == "banana_ambul" else line["qty"]) for line in context["confirmed"]["lines"]]
        return {"text": "Plan total 4604 LKR.", "calls": [{"name": "plan_day", "args": dict(context["confirmed"], lines=lines)}],
                "results": [{"name": "plan_day", "response": {"error": "Use the shopper's basket: you may leave items out, but not add items or change quantities."}}]}

    app.state.agent_runner = copies_pantry_quantities
    try:
        with TestClient(app) as http:
            why = _submit(http, http.get("/").text, "explain")
    finally:
        app.state.agent_runner = None
    assert "The agent re-planned with different inputs" not in why and "How this was calculated: 1 agent tool call" in why
    notice = ('<p class="notice">The agent tried to re-plan with different inputs (a different basket); '
              "the call was refused, so nothing was re-planned.</p>")
    assert why.count(notice) == 1 and why.index(notice) < why.index('<details class="how">')  # visible, not collapsed
    assert "The agent did not change your inputs." not in why
    assert _last(".bill thead th.num", "white-space") == "normal"  # long numeric headers wrap instead of overlapping


def test_each_plan_day_call_is_paired_with_its_own_response():
    refusal = {"error": "Use a day in the shopper's window."}

    async def mixed(question, context):
        ok = dict(context["confirmed"], day="2026-10-24")
        bad = dict(context["confirmed"], day="<img src=x onerror=alert(1)>", max_stores=5)
        return {"text": "Plan total 4604 LKR.",
                "calls": [{"name": "plan_day", "args": ok}, {"name": "load_offers", "args": {}},
                          {"name": "plan_day", "args": bad}, {"name": "plan_day", "args": bad}],
                "results": [{"name": "plan_day", "response": {"day": {"date": "2026-10-24"}}},
                            {"name": "load_offers", "response": {"error": "not this one"}},
                            {"name": "plan_day", "response": refusal}, {"name": "plan_day", "response": refusal}]}

    app.state.agent_runner = mixed
    try:
        with TestClient(app) as http:
            why = _submit(http, http.get("/").text, "explain")
    finally:
        app.state.agent_runner = None
    confirmed_day = re.search(r"<strong>Engine figures:</strong> Shop on \w+ ([\d-]+):", why).group(1)
    notices = re.findall(r'<p class="notice">(The agent (?:re-planned|tried)[^<]*)</p>', why)
    assert notices == [
        f"The agent re-planned with different inputs: day 2026-10-24 instead of {confirmed_day}. Its comparison is not the plan above.",
        f"The agent tried to re-plan with different inputs (day &lt;img src=x onerror=alert(1)&gt; instead of {confirmed_day}; "
        "max_stores 5 instead of 2); the call was refused, so nothing was re-planned.",
    ]  # paired by tool and order, the retried refusal shown once, model input escaped
    assert "<img src=x" not in why


def test_refused_then_completed_retries_and_other_tool_errors_are_disclosed_accurately():
    def notices_for(calls, results):
        async def runner(question, context):
            filled = [dict(c, args=c["args"](context["confirmed"])) for c in calls]
            return {"text": "Plan total 4604 LKR.", "calls": filled, "results": results}

        app.state.agent_runner = runner
        try:
            with TestClient(app) as http:
                why = _submit(http, http.get("/").text, "explain")
        finally:
            app.state.agent_runner = None
        return re.findall(r'<p class="notice">The agent (re-planned|tried)', why)

    other_day = lambda confirmed: dict(confirmed, day="2026-10-24")
    missing_store = lambda confirmed: {k: v for k, v in other_day(confirmed).items() if k != "usual_store"}
    error = {"error": "Invoking `plan_day()` failed: usual_store is missing."}
    done = {"day": {"date": "2026-10-24"}}
    # A failed call retried successfully with the same differences re-planned: no contradictory refused notice.
    assert notices_for([{"name": "plan_day", "args": missing_store}, {"name": "plan_day", "args": other_day}],
                       [{"name": "plan_day", "response": error}, {"name": "plan_day", "response": done}]) == ["re-planned"]
    # Another tool's error is never paired with a plan_day call.
    assert notices_for([{"name": "load_offers", "args": lambda c: {}}, {"name": "plan_day", "args": other_day}],
                       [{"name": "load_offers", "response": {"error": "offers unavailable"}}, {"name": "plan_day", "response": done}]) == ["re-planned"]
    # A retry listing the same cards in another order is the same request.
    cards = lambda order: (lambda c: {k: v for k, v in dict(c, banks=order).items() if k != "usual_store" or order[0] == "Commercial Bank"})
    assert notices_for([{"name": "plan_day", "args": cards(["Nations Trust Bank", "Commercial Bank"])},
                        {"name": "plan_day", "args": cards(["Commercial Bank", "Nations Trust Bank"])}],
                       [{"name": "plan_day", "response": error}, {"name": "plan_day", "response": done}]) == ["re-planned"]
    # A refused basket change is not hidden by a different basket change that completed.
    added = lambda c: dict(c, lines=c["lines"] + [{"sku_id": "papaya", "qty": 2}])
    left_out = lambda c: dict(c, lines=[l for l in c["lines"] if l["sku_id"] != "tomatoes"])
    assert notices_for([{"name": "plan_day", "args": added}, {"name": "plan_day", "args": left_out}],
                       [{"name": "plan_day", "response": error}, {"name": "plan_day", "response": done}]) == ["re-planned", "tried"]
    # Refused retries that would read identically (reordered lines, other baskets) are one sentence, not a repeated one.
    basket = lambda qty: (lambda c: dict(c, lines=[dict(l, qty=qty) if l["sku_id"] == "carrot" else l for l in reversed(c["lines"])]))
    assert notices_for([{"name": "plan_day", "args": basket(3)}, {"name": "plan_day", "args": basket(4)}],
                       [{"name": "plan_day", "response": error}, {"name": "plan_day", "response": error}]) == ["tried"]
    # A number written as 250.0 or "250" is the same request as 250.
    float_trip = lambda c: dict(other_day(c), trip_cost_lkr=float(c["trip_cost_lkr"]))
    assert notices_for([{"name": "plan_day", "args": float_trip}, {"name": "plan_day", "args": other_day}],
                       [{"name": "plan_day", "response": error}, {"name": "plan_day", "response": done}]) == ["re-planned"]
    assert notices_for([{"name": "plan_day", "args": lambda c: dict(c, max_stores=str(c["max_stores"]))}],
                       [{"name": "plan_day", "response": error}]) == []
    # The shopper's own request, reordered, split into rows, or with a card listed twice, changes nothing.
    same = lambda c: dict(c, lines=[dict(l, qty=l["qty"] / 2) for l in reversed(c["lines"])] * 2, banks=c["banks"] + c["banks"][:1])
    assert notices_for([{"name": "plan_day", "args": same}], [{"name": "plan_day", "response": done}]) == []
    # A refused day or card change is not hidden by a different completed day or card change.
    assert notices_for([{"name": "plan_day", "args": lambda c: dict(c, day="2026-10-25")}, {"name": "plan_day", "args": other_day}],
                       [{"name": "plan_day", "response": error}, {"name": "plan_day", "response": done}]) == ["re-planned", "tried"]
    assert notices_for([{"name": "plan_day", "args": lambda c: dict(c, banks=["HNB"])},
                        {"name": "plan_day", "args": lambda c: dict(c, banks=["Commercial Bank"])}],
                       [{"name": "plan_day", "response": error}, {"name": "plan_day", "response": done}]) == ["re-planned", "tried"]
    # Arguments that are not an object do not break the page.
    assert notices_for([{"name": "plan_day", "args": lambda c: [1, 2]}], [{"name": "plan_day", "response": done}]) == []
    # Two completed re-plans are each disclosed, as before.
    assert notices_for([{"name": "plan_day", "args": other_day}, {"name": "plan_day", "args": other_day}],
                       [{"name": "plan_day", "response": done}, {"name": "plan_day", "response": done}]) == ["re-planned", "re-planned"]


def test_card_differences_list_both_sides_sorted():
    from savvycart.http import _replan_differences

    confirmed = {"day": "2026-10-23", "max_stores": 2, "trip_cost_lkr": 250, "usual_store": "keells",
                 "banks": ["Nations Trust Bank", "Commercial Bank", "HNB"], "lines": []}
    assert _replan_differences({"banks": ["HNB", "Commercial Bank"]}, confirmed) == [
        "cards Commercial Bank, HNB instead of Commercial Bank, HNB, Nations Trust Bank"]
    basket = dict(confirmed, lines=[{"sku_id": "carrot", "qty": 2}])
    # Rows are summed before rounding, as the planner does: a split of the same basket is no change, a tiny addition is.
    assert _replan_differences({"lines": [{"sku_id": "carrot", "qty": 0.0005}] * 4 + [{"sku_id": "carrot", "qty": 1.998}]}, basket) == []
    assert _replan_differences({"lines": [{"sku_id": "carrot", "qty": 2}] + [{"sku_id": "carrot", "qty": 0.0004}] * 3}, basket) == [
        "a different basket"]
    # Quantities whose 3-decimal form equals their repr (1.998, 1.034) are numbers too.
    assert _replan_differences({"lines": [{"sku_id": "carrot", "qty": 1.034}]}, dict(confirmed, lines=[{"sku_id": "carrot", "qty": 1.034}])) == []
    assert _replan_differences({"trip_cost_lkr": 250.5}, dict(confirmed, trip_cost_lkr="250.5")) == []
    # Malformed rows are never silently dropped.
    for lines in ([{"sku_id": "carrot", "qty": 2}, {"sku_id": "carrot", "qty": "bad"}], [{"sku_id": "carrot", "qty": 2}, "junk"],
                  {"sku_id": "carrot", "qty": 2, "extra": True} | {"qty": None}, "carrot"):
        assert _replan_differences({"lines": lines}, basket) == ["a different basket"], lines


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
