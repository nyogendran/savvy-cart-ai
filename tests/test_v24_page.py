"""v2.4: Karuppan profile, recommendation first, simpler pantry rows, amber zero payout, touch targets (SC-027)."""

from __future__ import annotations

import html
import re
from datetime import date as _date
from pathlib import Path

from fastapi.testclient import TestClient

from savvycart import http as page_module
from savvycart.http import V2_BANNER, _parse_state, _recommendation, _render_pantry, _timing_text, app

from test_v21_page import _sections, _submit

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "src" / "savvycart" / "static" / "app.css").read_text(encoding="utf-8")


def _text(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _profile(page: str) -> re.Match[str]:
    match = re.search(r'<aside class="profile( compact)?" aria-label="Demo household">(.*?)</aside>', page, re.S)
    assert match, "no profile card"
    return match


def _how(page: str) -> tuple[int, int]:
    start = page.index('<details class="how">')
    return start, page.index("</details>", start)


def _css_rules() -> list[tuple[list[str], str]]:
    body = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    return [([" ".join(s.split()) for s in selectors.split(",")], block) for selectors, block in re.findall(r"([^{}]+)\{([^{}]*)\}", body)]


def _last(selector: str, prop: str) -> str | None:
    value = None
    for selectors, block in _css_rules():
        if selector in selectors:
            for found in re.findall(rf"(?:^|;|\s){re.escape(prop)}:\s*([^;]+)", block):
                value = found.strip()
    return value


def test_profile_card_reflects_current_selections_on_every_step():
    with TestClient(app) as http:
        home = http.get("/").text
        pages = {"pantry": home}
        for action in ("wallet", "plan", "explain", "approve", "offer"):
            pages[action] = _submit(http, home, action)
        changed = _submit(http, pages["wallet"], "plan", [("budget", "9000"), ("usual_store", "cargills"),
                                                          ("bank", "Commercial Bank"), ("bank", "HNB")], drop=("bank",))
        one = _submit(http, pages["wallet"], "plan", [("bank", "HNB")], drop=("bank",))
        none = _submit(http, pages["wallet"], "plan", drop=("bank",))
    for name, page in pages.items():
        card = _profile(page)
        assert bool(card.group(1)) == (name != "pantry"), name  # full on Pantry, compact elsewhere
        assert re.search(r'<svg [^>]*aria-hidden="true"', card.group(2)), name
        assert not re.search(r"href|src=|http|url\((?!#)", card.group(2)), name  # no external asset
        text = _text(card.group(2))
        assert "Karuppan's household · Colombo" in text and "Fictional demo profile" in text, name
        assert "LKR 12,000 budget · 3 cards · Usually shops at Keells" in text, name
        assert page.index("<form") < page.index("<aside") < page.index('<nav class="steps"'), name
        assert '<section class="step"' not in card.group(2), name
    assert "LKR 9,000 budget · 2 cards · Usually shops at Cargills" in _text(_profile(changed).group(2))
    assert "LKR 12,000 budget · 1 card · Usually shops at Keells" in _text(_profile(one).group(2))
    assert "LKR 12,000 budget · no cards · Usually shops at Keells" in _text(_profile(none).group(2))


def test_sample_data_notice_stays_visible_with_details_expandable():
    with TestClient(app) as http:
        home = http.get("/").text
        plan = _submit(http, home, "plan")
    for page in (home, plan):
        banner = re.search(r'<div class="banner" id="banner"><div class="wrap">(.*?)</div></div>', page, re.S).group(1)
        details = banner.index("<details>")
        assert "Sample data, not live; savings are simulated." in banner[:details]
        assert html.escape(V2_BANNER, quote=True) in banner[details:]


def test_plan_leads_with_a_recommendation_built_from_the_engine_plan(monkeypatch):
    with TestClient(app) as http:
        home = http.get("/").text
        wallet = _submit(http, home, "wallet")
        plan = _submit(http, home, "plan")
        control = _submit(http, wallet, "refused")
        hnb = _submit(http, wallet, "plan", [("bank", "HNB")], drop=("bank",))
        hnb_why, hnb_approve = (_submit(http, hnb, action) for action in ("explain", "approve"))
        default_why, default_approve = (_submit(http, plan, action) for action in ("explain", "approve"))
        real = page_module.engine_plan_day
        monkeypatch.setattr(page_module, "engine_plan_day", lambda *a, **k: {**real(*a, **k), "solver_status": "FEASIBLE"})
        feasible = _submit(http, home, "plan")
    rec = re.search(r'</h2><p class="recommendation" id="plan-recommendation">(.*?)</p>', plan).group(1)
    assert plan.index('id="plan-recommendation"') < plan.index('class="metric')
    weekday, iso = re.search(r'<h2 id="plan-h">3\. Plan for (\w+) (\d{4}-\d\d-\d\d)</h2>', plan).groups()
    day = _date.fromisoformat(iso)
    stores = re.findall(r'<article class="bill" data-store="(\w+)"><header><h3>([^<]+)</h3>(.*?)</header>', plan, re.S)
    assert stores and rec.startswith(f"Shop on {weekday} {day.day} {day:%b} at ")
    for _, name, header in stores:
        assert name in rec.split(".")[0]
        card = re.search(r'<span class="card-used">Pay with ([^<]+)</span>', header)
        if card:
            assert f"Pay with {card.group(1)} at {name}." in rec  # published offers carry no qualifier
    assert rec.count("Pay with") == sum('class="card-used"' in h for _, _, h in stores) > 0
    assert 'class="notice">The optimizer stopped' not in plan
    hnb_rec = re.search(r'id="plan-recommendation">(.*?)</p>', hnb).group(1)
    assert re.search(r"Pay with HNB credit at \w+ \(fictional demo offer\)\.", hnb_rec), hnb_rec
    note = '<p class="notice">HNB card offers in this plan are fictional demo offers, not published by the bank.</p>'
    assert re.search(r'<p class="recap"><strong>Engine figures:</strong> [^<]*</p>' + re.escape(note), hnb_why)
    assert re.search(r'<p class="recap">[^<]*</p>' + re.escape(note), hnb_approve)
    assert hnb_why.count(note) == hnb_approve.count(note) == 1
    assert "fictional demo offers, not published" not in default_why + default_approve + plan
    # The default plan holds HNB without paying with it; every visible mention of its offer still says it is fictional.
    visible = _text(re.sub(r"<details.*?</details>", "", plan.split('<section class="step" id="plan"')[1], flags=re.S))
    assert "HNB (fictional demo offer) at Cargills: needs" in visible
    assert not re.findall(r"HNB(?! \(fictional demo offer\))", visible)
    control_rec = re.search(r'id="plan-recommendation">(.*?)</p>', control).group(1)
    assert control_rec.startswith("Control basket, priced with every demo card, one store, and Keells as the usual store: Shop on ")
    assert control_rec.endswith("No card offer applies to this basket.") and "Pay with" not in control_rec
    notice = re.search(r'id="plan-recommendation">.*?</p><p class="notice">([^<]+)</p>', feasible).group(1)
    assert notice == "The optimizer stopped before proving this is the cheapest plan (status FEASIBLE)."
    assert _recommendation({"stores": [], "day": {"weekday": "friday", "date": "2026-10-23"}}) == "No store can price this basket."
    three = {"day": {"weekday": "friday", "date": "2026-10-23"},
             "stores": [{"store_id": s, "card": None} for s in ("keells", "cargills", "glomark")]}
    assert _recommendation(three) == "Shop on Friday 23 Oct at Keells, Cargills and Glomark. No card offer applies to this basket."
    for page in (plan, control):
        start, end = _how(page)
        for detail in ("CP-SAT", "Engine steps:", "per extra store"):
            assert detail in page[start:end] and detail not in page[:start] + page[end:], detail


def test_pantry_rows_show_a_short_timing_label_and_expandable_history():
    with TestClient(app) as http:
        home = http.get("/").text
    upcoming = home.split("<h3>Due or soon")[1].split("<details><summary>Later")[0]
    rows = re.findall(r'<div class="item">(.*?)</div>', upcoming, re.S)
    assert rows
    names = []
    for row in rows:
        found = re.search(r'<details class="reason"><summary>([^<]+)<span class="sr-only">: ([^<]+)</span></summary>'
                          r"<p>(Bought on [^<]+)</p></details>$", row)
        assert found, row
        label, name, sentence = found.groups()
        assert f'<label class="name" for="sku_' in row and f">{name} <span" in row  # the summary names its own item
        names.append(f"{label}: {name}")
        assert row.index('type="number"') < row.index('<details class="reason">')  # after the quantity
        when = re.search(r"\((today|in (\d+) days?|overdue by (\d+) days?)\)", sentence)
        if when.group(1) == "today":
            assert label == "Due today"
        elif when.group(2):
            assert label == f"Due in {when.group(2)} day{'s' if when.group(2) != '1' else ''}"
        else:
            assert label == f"Overdue by {when.group(3)} day{'s' if when.group(3) != '1' else ''}"
    assert any(n.startswith("Overdue by 19 days: ") for n in names)  # the stale row uses the overdue label
    assert len(names) == len(set(names))  # every toggle has a distinct accessible name
    labels = {left: _timing_text({"days_left": left}) for left in (-2, -1, 0, 1, 2)}
    assert labels == {-2: "Overdue by 2 days", -1: "Overdue by 1 day", 0: "Due today", 1: "Due in 1 day", 2: "Due in 2 days"}
    unknown = {"sku_id": "papaya", "name": "Papaya", "display_status": "unknown", "status": "unknown", "checked": False,
               "qty": 1, "divisible": True, "reason": "Bought once, so there is not enough history yet."}
    row = re.search(r'<div class="item">(.*?)</div>', _render_pantry([unknown], _parse_state({}), None), re.S).group(1)
    assert row.endswith('<span class="reason">Bought once, so there is not enough history yet.</span>')


def test_zero_payout_is_amber_and_offer_check_returns_to_the_plan():
    back = '<button type="submit" name="action" value="plan" class="primary">Go to my shopping plan</button>'
    with TestClient(app) as http:
        sample = _submit(http, _submit(http, http.get("/").text, "offer"), "offer_sample")
        paying = _submit(http, sample, "offer_check", [("o_min", "0")])
        plan = _submit(http, sample, "plan")
    assert "The terms pay you LKR 0" in _text(sample) and '<div class="truth zero">' in sample
    paid = int(re.search(r'<div class="truth"><div class="label">The terms pay you</div><div class="value">LKR ([\d,]+)</div>',
                         paying).group(1).replace(",", ""))
    assert paid > 0 and "truth zero" not in paying
    held = sample.index("</p>", sample.index('<p class="ok-note">', sample.index('class="reality"'))) + len("</p>")
    assert sample[held:].startswith(f'<div class="actions">{back}</div>')  # right after the result
    assert sample.count(back) == 1
    assert '<button type="submit" name="action" value="plan" class="primary">Next: plan my shopping</button>' in sample
    assert _sections(plan) == ["plan"]
    assert _last(".truth.zero", "background") == "var(--warn-soft)" and _last(".truth.zero .value", "color") == "var(--warn)"


def test_agent_tool_calls_sit_behind_how_this_was_calculated():
    async def three_calls(question, context):
        return {"text": "Plan total 4609 LKR.", "calls": [{"name": "get_pantry", "args": {}}, {"name": "load_offers", "args": {}},
                                                          {"name": "plan_day", "args": context["confirmed"]}], "results": []}

    async def replan(question, context):
        other = dict(context["confirmed"], day="2026-10-29" if context["confirmed"]["day"] != "2026-10-29" else "2026-10-28")
        return {"text": "Another day.", "calls": [{"name": "plan_day", "args": other}], "results": []}

    async def no_calls(question, context):
        return {"text": "Plan total 4609 LKR.", "calls": [], "results": []}

    pages = []
    for runner in (three_calls, replan, no_calls):
        app.state.agent_runner = runner
        try:
            with TestClient(app) as http:
                pages.append(_submit(http, http.get("/").text, "explain"))
        finally:
            app.state.agent_runner = None
    calls, replanned, none = pages
    start, end = _how(calls)
    assert calls[start:end].startswith('<details class="how"><summary>How this was calculated: 3 agent tool calls</summary>')
    assert start < calls.index('<ul class="tools" id="agent-tools">') < end
    assert "The agent did not change your inputs." in calls[start:end]
    assert calls.index('<p id="explanation-text">') < start
    start, end = _how(replanned)
    assert "How this was calculated: 1 agent tool call</summary>" in replanned[start:end]
    notice = replanned.index('<p class="notice">The agent re-planned with different inputs')
    assert notice < start and "did not change your inputs" not in replanned
    assert "How this was calculated: no agent tool calls</summary>" in none and "did not change your inputs" not in none


def test_touch_targets_are_at_least_44px():
    for selector in ("button", "select", 'input[type="number"]', 'input[type="text"]', 'input[type="date"]',
                     "button.chip", ".check", "nav.steps li", "nav.steps li button.linklike", "details summary"):
        assert _last(selector, "min-height") == "44px", selector
    # The only sub-44px button rule is the link-style button, which renders only in the step pills (overridden above).
    small = [s for selectors, block in _css_rules() for s in selectors
             if any(v.strip() != "44px" for v in re.findall(r"min-height:\s*([^;]+)", block))
             and re.search(r"\b(button|select|input)\b", s)]
    assert small == ["button.linklike"]
    assert (ROOT / "src" / "savvycart" / "http.py").read_text(encoding="utf-8").count('class="linklike"') == 1
    for box in ('input[type="checkbox"]', 'input[type="radio"]'):
        assert _last(box, "width") == "22px" and _last(box, "height") == "22px", box
    assert _last(".scroll", "overflow-x") == "auto"
    with TestClient(app) as http:
        home = http.get("/").text
        plan = _submit(http, home, "plan")
        offer = _submit(http, _submit(http, home, "offer"), "offer_sample")
    assert plan.count('<div class="scroll"><table>') == plan.count('<article class="bill"') > 0
    assert offer.count('<div class="scroll"><table class="lines">') == offer.count('<table class="lines">') == 1
