"""v2.6: truthful category offers, responsive Gemini steps, a mock cart, plan with a checked card, leaner calls (SC-032)."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from savvycart import agent, offercheck
from savvycart import http as page_module
from savvycart.http import AGENT_TIMEOUT_SECONDS, _v2_catalog, app

from test_v21_page import FORM, _submit
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
SMS = {"bank": "Mastercard", "card_products": "Mastercard Credit Cards", "store_name": "Keells",
       "headline": "Save 25% at Keells on Fresh Meat, Fruits & Vegetables", "percent_off": 25, "days": ["Sunday"],
       "minimum_bill_lkr": 5000, "max_discount_lkr": 1500, "excluded_items": [], "applies_only_to": ["Fresh Meat", "Fruits", "Vegetables"],
       "valid_until": "31 Oct", "combines_with_store_offers": None}


def _text(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


class _Reader:
    def __init__(self, answer):
        self.answer = answer

    def extract_offer(self, text, image, schema, prompt):
        return self.answer


@pytest.fixture(autouse=True)
def _clean_state():
    app.state.model_rate_limiter = app.state.agent_runner = app.state.model_client = None
    page_module._answers.clear()
    yield
    app.state.model_rate_limiter = app.state.agent_runner = app.state.model_client = None
    page_module._answers.clear()


def _read(http, raw):
    page = _submit(http, http.get("/").text, "offer")
    app.state.model_client = _Reader(raw)
    try:
        return _submit(http, page, "offer_read", [("o_text", "an SMS")])
    finally:
        app.state.model_client = None


def test_category_limited_offer_pays_only_covered_items():
    with TestClient(app) as http:
        read = _read(http, SMS)
        recheck = _submit(http, read, "offer_check")
        odd = _read(http, {**SMS, "applies_only_to": ["Electronics"]})
    text = _text(read)
    assert "This offer pays LKR 407, not LKR 1,483: 5 of your 11 items do not count." in text
    for item in ("Dish wash bar 200 g", "Sandwich bread 450 g", "Full cream UHT milk 1 L"):
        assert re.search(rf"{re.escape(item)} LKR [\d,]+ - ✗ Not covered: the offer is for fresh only", text), item
    assert re.search(r"Tomatoes LKR [\d,]+ LKR [\d,]+ ✓ Counts", text)
    assert "Applies only to Fresh Meat, Fruits, Vegetables" in text
    assert 'name="o_incl" value="fresh" checked' in read and 'name="o_incl" value="staple" checked' not in read
    assert "This offer pays LKR 407" in _text(recheck)  # the confirm form keeps the category limit
    rule, _ = offercheck.validate_rule(SMS, _v2_catalog(), "test", date(2026, 10, 22))
    assert rule["include_categories"] == ["fresh"] and offercheck.planner_offer(rule)["include_categories"] == ["fresh"]
    assert "“Electronics” matches no category in this catalog, so items under it are not counted." in _text(odd)
    assert "The terms pay you LKR 0" in _text(odd)  # nothing counts rather than everything
    assert "(not stated in the offer)" in _text(recheck)  # rechecking keeps an unstated term unstated
    with TestClient(app) as http:
        odd_recheck = _submit(http, odd, "offer_check")
        odd_plan = _submit(http, odd, "offer_plan")
    assert "The terms pay you LKR 0" in _text(odd_recheck) and 'value="none" checked' in odd_recheck  # never widened to the bill
    assert "the offer you checked)" not in " ".join(re.findall(r'<span class="card-used">([^<]+)', odd_plan))


def test_offer_end_dates_networks_and_unstated_terms():
    today = date(2026, 10, 22)
    assert offercheck.read_end_date("31 Oct", today) == ("2026-10-31", True)
    assert offercheck.read_end_date("Oct 31", today) == ("2026-10-31", True)
    assert offercheck.read_end_date("31/10", today) == ("2026-10-31", True)
    assert offercheck.read_end_date("1 Jan", today) == ("2027-01-01", True)  # already past this year
    assert offercheck.read_end_date("2026-11-05", today) == ("2026-11-05", False)
    assert offercheck.read_end_date("soon", today) == (None, False)
    assert offercheck.read_end_date("31 Oct 2025", today) == ("2025-10-31", False)  # a printed year is honoured
    assert offercheck.read_end_date("till 31st October", today) == ("2026-10-31", True)
    assert offercheck.read_end_date("Marked 5 days", today) == (None, False)
    assert offercheck.read_end_date("29 Feb", today) == ("2028-02-29", True)
    for issuer in ("NDB Mastercard", "DFCC Visa", "Advisa Credit"):
        assert not any("card network" in n for n in offercheck.validate_rule({**SMS, "bank": issuer}, _v2_catalog(), "t", today)[1]), issuer
    multi = offercheck.validate_rule({**SMS, "applies_only_to": ["Vegetable oil"]}, _v2_catalog(), "t", today)
    assert multi[0]["include_categories"] == ["fresh", "staple"] and any("untick what does not apply" in n for n in multi[1])
    rule, notes = offercheck.validate_rule(SMS, _v2_catalog(), "test", today)
    assert rule["valid_to"] == "2026-10-31" and "End date read as 2026-10-31." in notes
    assert "Mastercard is a card network, not a bank: the offer is for any Mastercard card of the kind named. Check which of your cards it is." in notes
    assert "The terms do not say whether it combines with store promotions; checked as if it does." in notes
    assert rule["stacks_with_promotions"] is True and rule["stacks_stated"] is False
    _, bank_notes = offercheck.validate_rule({**SMS, "bank": "Commercial Bank Mastercard"}, _v2_catalog(), "test", today)
    assert not any("card network" in n for n in bank_notes)
    with TestClient(app) as http:
        read = _read(http, SMS)
        stated = _read(http, {**SMS, "combines_with_store_offers": True})
    assert "Combines with store promotions yes (not stated in the offer)" in _text(read)
    assert 'name="o_stack_unstated"' in read and "(not stated in the offer)" not in stated


def test_why_opens_instantly_and_the_agent_runs_on_ask():
    runs = []

    async def runner(question, context):
        runs.append(question)
        other = dict(context["confirmed"], max_stores=1)
        return {"text": "**Keells and Cargills** is cheapest. * Keells for fresh. ### Cards Plan total 4604 LKR.",
                "calls": [{"name": "plan_day", "args": other}], "results": [{"name": "plan_day", "response": {"day": {}}}]}

    app.state.agent_runner = runner
    with TestClient(app) as http:
        plan = _submit(http, http.get("/").text, "plan")
        why = _submit(http, plan, "why")
        asked = _submit(http, why, "explain")
        again = _submit(http, why, "explain")
    assert '<button type="submit" name="action" value="why" class="primary">Next: explain this plan</button>' in plan
    assert runs == ["Explain to the shopper, in a few short sentences, why this is the cheapest way to buy these groceries: "
                    "which store and card for which items, and what they save against their usual store. "
                    "If another day or fewer stores would change the answer, you may compare with plan_day and say so."]  # once: cached
    assert "Engine explanation. Ask the agent below for Gemini&#x27;s view; it can take up to a minute." in why
    assert "Answer from the ADK agent (Gemini)" in asked and asked == again
    answer = re.search(r'<p id="explanation-text">(.*?)</p>', asked, re.S).group(1)
    assert answer.startswith("<strong>Keells and Cargills</strong> is cheapest.<br>• Keells for fresh.") and "###" not in answer and "**" not in answer
    assert "The agent re-planned with different inputs: at most 1 store instead of 2." in asked
    assert AGENT_TIMEOUT_SECONDS == 100
    pills = re.search(r'<nav class="steps".*?</nav>', _submit_approve(plan), re.S).group(0)
    assert 'value="why">Why</button>' in pills


def _submit_approve(plan):
    with TestClient(app) as http:
        return _submit(http, plan, "approve")


def test_busy_script_and_plain_answers():
    with TestClient(app) as http:
        home = http.get("/").text
        js = http.get(re.search(r'<script src="(/static/app\.js\?v=\w+)" defer></script>', home).group(1)).text
    assert '<div id="busy" class="busy" role="status" aria-live="polite" hidden>' in home
    assert "if (sent) { e.preventDefault(); return; }" in js  # a second submit is blocked
    assert "setTimeout(function () { setButtons(true); }, 0);" in js  # disabled after the browser reads the clicked button
    for action in ("offer_read", "explain", "upload"):
        assert re.search(rf"{action}: \"[^\"]+This can take up to a minute\.\"", js), action
    assert 's.name === "question_chip" ? "explain"' in js and "e.persisted" in js
    assert page_module._answer_html("a <b> `x` 5 - 3") == "a &lt;b&gt; <code>x</code> 5 - 3"  # mid-sentence dash stays
    assert page_module._answer_html("- First. * Second: - third") == "• First.<br>• Second:<br>• third"
    assert page_module._answer_html("**<img src=x onerror=alert(1)>**") == "<strong>&lt;img src=x onerror=alert(1)&gt;</strong>"
    assert "<strong><code>" not in page_module._answer_html("**`x**`")


def test_approve_shows_a_mock_cart_per_store():
    skus = {s["id"]: s for s in _v2_catalog()["skus"]}
    with TestClient(app) as http:
        plan_page = _submit(http, http.get("/").text, "plan")
        pickup = _submit(http, plan_page, "approve")
        delivery = _submit(http, pickup, "approve", [("fulfilment", "delivery")])
    state = page_module._parse_state({})
    plan, _ = page_module._engine_plan(state, page_module._pantry_view(state))
    for page, fee in ((pickup, 0), (delivery, 350)):
        carts = dict(re.findall(r'<article class="cart" data-store="(\w+)">(.*?)</article>', page, re.S))
        assert set(carts) == {b["store_id"] for b in plan["stores"]}
        for bill in plan["stores"]:
            cart = carts[bill["store_id"]]
            rows = re.findall(r'<tr><td>([^<]+)</td><td class="num">([^<]+)</td><td class="num">([\d,]+)</td><td class="num">([\d,]+)</td></tr>', cart)
            assert len(rows) == len(bill["lines"])
            for line, (name, qty, unit, amount) in zip(bill["lines"], rows):
                assert html.unescape(name) == line["name"] and int(amount.replace(",", "")) == line["promoted_lkr"]
                assert int(unit.replace(",", "")) == skus[line["sku_id"]]["prices"][bill["store_id"]]["amount_lkr"]
            assert f'Bill total</td><td class="num">LKR {bill["bill_lkr"]:,}' in cart
            assert ("Delivery fee (assumption)" in cart) == bool(fee)
        grand = (plan["effective_cost_lkr"] + fee * len(plan["stores"])) if fee else sum(b["bill_lkr"] for b in plan["stores"])
        assert f'<p class="grand">Total LKR {grand:,}' in page
        if fee:  # one total on the page: the cart's equals "Total with delivery"
            assert f"Total with delivery: <strong>LKR {grand:,}</strong>" in page
            assert f"(includes the LKR {plan['extra_trip_cost_lkr']:,} extra-trip estimate from your plan)" in page
        assert '<button type="button" id="copy-cart">Copy list</button>' in page and 'href="https://wa.me/?text=' in page
        assert ">Update my cart</button>" in page and "MOCK" in page and "No order is sent." in page
        assert re.search(r"Cart reference \(<strong>MOCK</strong>\): preview-\w+\.", page)
    assert f"plus LKR {plan['extra_trip_cost_lkr']:,} for the extra trip, your estimate" in pickup
    assert "for the extra trip" not in delivery.split('<p class="grand">')[1].split("</p>")[0]


def test_plan_with_a_checked_card():
    better = {"bank": "Commercial Bank", "card_products": "Test Credit", "store_name": "Keells", "headline": "20% off the whole bill",
              "percent_off": 20, "days": ["Saturday"], "minimum_bill_lkr": 1000, "max_discount_lkr": None, "excluded_items": [],
              "valid_until": None, "combines_with_store_offers": True}
    with TestClient(app) as http:
        wallet = _submit(http, http.get("/").text, "wallet")
        no_cards = _submit(http, wallet, "wallet", drop=("bank",))
        offer = _submit(http, no_cards, "offer")
        app.state.model_client = _Reader(better)
        try:
            read = _submit(http, offer, "offer_read", [("o_text", "an offer")])
        finally:
            app.state.model_client = None
        plan = _submit(http, read, "offer_plan")
        why = _submit(http, plan, "why")
        approve = _submit(http, why, "approve")
        dropped = _submit(http, plan, "drop_offer")
    assert '<button type="submit" name="action" value="offer_plan">Plan with this card on Saturday 24 Oct</button>' in read
    assert "3. Plan for Saturday 2026-10-24" in plan
    labels = re.findall(r'<span class="card-used">([^<]+)</span>', plan)
    assert "Pay with Test Credit (the offer you checked)" in labels
    assert not any(l.startswith("Pay with Commercial Bank") for l in labels)  # the key never unlocks that bank's real offers
    assert "This plan uses the offer you checked" in plan and "Pay with Test Credit (the offer you checked) at Keells." in plan
    for page in (why, approve):
        assert "This plan uses the offer you checked" in page and "Test Credit (the offer you checked)" in page
    assert "the offer you checked" not in dropped and 'name="held_offer"' not in dropped
    key = "Checked offer (Commercial Bank)"
    held = {**offercheck.planner_offer(offercheck.validate_rule(better, _v2_catalog(), "t", date(2026, 10, 22))[0]),
            "id": "checked_offer", "bank": key, "source": "checked"}
    lines = [{"sku_id": "carrot", "qty": 1.0}, {"sku_id": "tomatoes", "qty": 2.0}, {"sku_id": "bread_450g", "qty": 10.0}]
    session_plan = agent._session_offer_tools([held])[1](lines, "2026-10-24", [key], 1, 250, "keells")
    assert "error" not in session_plan and session_plan["stores"][0]["card"]["bank"] == key
    assert "error" in agent.plan_day(lines, "2026-10-24", [key], 1, 250, "keells")  # unknown outside this session
    raw = page_module._rule_raw(offercheck.validate_rule(better, _v2_catalog(), "t", date(2026, 10, 22))[0])
    with TestClient(app) as http:
        tampered = _submit(http, plan, "plan", [("held_offer", json.dumps({**raw, "percent_off": 95}))])
        injected = _submit(http, plan, "plan", [("held_offer", json.dumps({**raw, "exclude_sku_ids": ["carrot", "<script>", "nope"]}))])
        bad_day = http.post("/ui", content=urlencode([("action", "plan"), ("day", "zzz"), ("held_offer", json.dumps(raw))]), headers=FORM)
        moved = _submit(http, plan, "plan", [("day", "2026-10-23")])
    assert "the offer you checked" not in tampered  # out-of-range terms are dropped, not trusted
    carried = json.loads(html.unescape(re.search(r'name="held_offer" value="([^"]*)"', injected).group(1)))
    assert carried["exclude_sku_ids"] == ["carrot"]  # only catalog ids survive
    assert bad_day.status_code == 200  # a typed day never reaches the engine unchecked
    assert "The offer you checked is not used</strong>: it is valid on Saturday, not Friday." in moved


def test_answer_cache_separates_checked_offers_and_expires(monkeypatch):
    runs = []

    async def runner(question, context):
        runs.append(question)
        return {"text": "Plan total 4604 LKR.", "calls": [], "results": []}

    app.state.agent_runner = runner
    offer = {"bank": "Commercial Bank", "card_products": "Test", "store_name": "Keells", "headline": "x", "percent_off": 5,
             "days": ["Saturday"], "minimum_bill_lkr": 900000, "max_discount_lkr": None, "excluded_items": [], "combines_with_store_offers": True}
    with TestClient(app) as http:
        pages = []
        for rate in (5, 20):  # neither is used (unreachable minimum), so the plans are identical
            app.state.model_client = _Reader({**offer, "percent_off": rate})
            try:
                read = _submit(http, _submit(http, http.get("/").text, "offer"), "offer_read", [("o_text", "x")])
            finally:
                app.state.model_client = None
            pages.append(_submit(http, _submit(http, read, "offer_plan"), "explain"))
        assert len(runs) == 2  # different checked terms are different contexts
        _submit(http, pages[1], "explain")
        assert len(runs) == 2  # the same context is served from the cache
        later = page_module.time.time() + page_module.ANSWER_TTL_SECONDS + 1
        monkeypatch.setattr(page_module.time, "time", lambda: later)
        _submit(http, pages[1], "explain")
    assert len(runs) == 3  # and expires


def test_engine_cache_direct_approve_and_versioned_css(monkeypatch):
    calls = []
    real = page_module.engine_plan_day

    def counting(*args, **kwargs):
        calls.append(args[3])
        return real(*args, **kwargs)

    monkeypatch.setattr(page_module, "engine_plan_day", counting)

    async def no_loopback(*args, **kwargs):
        raise AssertionError("approve must not call this app over HTTP")

    monkeypatch.setattr(page_module, "_internal_post", no_loopback)
    with TestClient(app) as http:
        home = http.get("/").text
        first = _submit(http, home, "plan")
        count = len(calls)
        second = _submit(http, home, "plan")
        approve = _submit(http, first, "approve")
    assert count > 0 and len(calls) == count and first == second  # the second identical plan is served from the cache
    assert "Cart reference" in approve
    digest = hashlib.sha256((ROOT / "src" / "savvycart" / "static" / "app.css").read_bytes()).hexdigest()[:10]
    assert f'<link rel="stylesheet" href="/static/app.css?v={digest}">' in home
    real_day = page_module.engine_plan_day
    unproven = []
    monkeypatch.setattr(page_module, "engine_plan_day", lambda *a, **k: unproven.append(1) or {**real_day(*a, **k), "solver_status": "FEASIBLE"})
    with TestClient(app) as http:
        _submit(http, home, "plan")
        once = len(unproven)
        _submit(http, home, "plan")
    assert once and len(unproven) == 2 * once  # an unproven solve is never served from the cache
