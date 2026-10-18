"""v2.4: Karuppan profile, recommendation first, simpler pantry rows, amber zero payout, touch targets (SC-027)."""

from __future__ import annotations

import html
import re
from pathlib import Path

from fastapi.testclient import TestClient

from savvycart.http import V2_BANNER, _recommendation, app

from test_v21_page import _sections, _submit

CSS = (Path(__file__).resolve().parents[1] / "src" / "savvycart" / "static" / "app.css").read_text(encoding="utf-8")


def _text(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _profile(page: str) -> re.Match[str]:
    match = re.search(r'<aside class="profile( compact)?" aria-label="Demo household">(.*?)</aside>', page, re.S)
    assert match, "no profile card"
    return match


def _how(page: str) -> tuple[int, int]:
    start = page.index('<details class="how">')
    return start, page.index("</details>", start)


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
        text = _text(card.group(2))
        assert "Karuppan's household · Colombo" in text and "Fictional demo profile" in text, name
        assert "LKR 12,000 budget · 3 cards · Usually shops at Keells" in text, name
        assert page.index("<aside") < page.index('<nav class="steps"'), name
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


def test_plan_leads_with_a_recommendation_built_from_the_engine_plan():
    with TestClient(app) as http:
        home = http.get("/").text
        plan = _submit(http, home, "plan")
        control = _submit(http, _submit(http, home, "wallet"), "refused")
    rec = re.search(r'<p class="recommendation" id="plan-recommendation">(.*?)</p>', plan).group(1)
    assert plan.index('id="plan-recommendation"') < plan.index('class="metric')
    weekday, date = re.search(r'<h2 id="plan-h">3\. Plan for (\w+) (\d{4}-\d\d-\d\d)</h2>', plan).groups()
    month = {"10": "Oct"}[date[5:7]]
    stores = re.findall(r'<article class="bill" data-store="(\w+)"><header><h3>([^<]+)</h3>(.*?)</header>', plan, re.S)
    assert stores and rec.startswith(f"Shop on {weekday} {int(date[8:])} {month} at ")
    for _, name, header in stores:
        assert name in rec.split(".")[0]
        card = re.search(r'<span class="card-used">Pay with ([^<]+)</span>', header)
        if card:
            assert f"Pay with {card.group(1)} at {name}." in rec
    assert rec.count("Pay with") == sum('class="card-used"' in h for _, _, h in stores) > 0
    control_rec = re.search(r'id="plan-recommendation">(.*?)</p>', control).group(1)
    assert control_rec.endswith("No card offer applies to this basket.") and "Pay with" not in control_rec
    assert _recommendation({"stores": [], "day": {"weekday": "friday", "date": "2026-10-23"}}) == "No store can price this basket."
    three = {"day": {"weekday": "friday", "date": "2026-10-23"},
             "stores": [{"store_id": s, "card": None} for s in ("keells", "cargills", "glomark")]}
    assert _recommendation(three) == "Shop on Friday 23 Oct at Keells, Cargills and Glomark. No card offer applies to this basket."
    for page in (plan, control):
        start, end = _how(page)
        assert "CP-SAT" in page[start:end] and "CP-SAT" not in page[:start] + page[end:]


def test_pantry_rows_show_a_short_timing_label_and_expandable_history():
    with TestClient(app) as http:
        home = http.get("/").text
    upcoming = home.split("<h3>Due or soon")[1].split("<details><summary>Later")[0]
    rows = re.findall(r'<div class="item">(.*?)</div>', upcoming, re.S)
    assert rows
    for row in rows:
        found = re.search(r'<details class="reason"><summary>([^<]+)</summary><p>(Bought on [^<]+)</p></details>$', row)
        assert found, row
        label, sentence = found.groups()
        assert row.index('type="number"') < row.index('<details class="reason">')  # after the quantity
        when = re.search(r"\((today|in (\d+) days?|overdue by (\d+) days?)\)", sentence)
        if "Not bought for a while" in sentence:
            assert label.startswith("Last bought ")
        elif when.group(1) == "today":
            assert label == "Due today"
        elif when.group(2):
            assert label == f"Due in {when.group(2)} day{'s' if when.group(2) != '1' else ''}"
        else:
            assert label == f"Overdue by {when.group(3)} day{'s' if when.group(3) != '1' else ''}"


def test_zero_payout_is_amber_and_offer_check_returns_to_the_plan():
    back = '<button type="submit" name="action" value="plan" class="primary">Back to my shopping plan</button>'
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
    assert sample.count(back) == 2  # after the result and in the bottom nav
    assert _sections(plan) == ["plan"]


def test_agent_tool_calls_sit_behind_how_this_was_calculated():
    async def three_calls(question, context):
        return {"text": "Plan total 4609 LKR.", "calls": [{"name": "get_pantry", "args": {}}, {"name": "load_offers", "args": {}},
                                                          {"name": "plan_day", "args": context["confirmed"]}], "results": []}

    async def replan(question, context):
        other = dict(context["confirmed"], day="2026-10-29" if context["confirmed"]["day"] != "2026-10-29" else "2026-10-28")
        return {"text": "Another day.", "calls": [{"name": "plan_day", "args": other}], "results": []}

    pages = []
    for runner in (three_calls, replan):
        app.state.agent_runner = runner
        try:
            with TestClient(app) as http:
                pages.append(_submit(http, http.get("/").text, "explain"))
        finally:
            app.state.agent_runner = None
    calls, replanned = pages
    start, end = _how(calls)
    assert calls[start:end].startswith('<details class="how"><summary>How this was calculated: 3 agent tool calls</summary>')
    assert start < calls.index('<ul class="tools" id="agent-tools">') < end
    assert "The agent did not change your inputs." in calls[start:end]
    assert calls.index('<p id="explanation-text">') < start
    start, end = _how(replanned)
    assert "How this was calculated: 1 agent tool call</summary>" in replanned[start:end]
    notice = replanned.index('<p class="notice">The agent re-planned with different inputs')
    assert notice < start and "did not change your inputs" not in replanned


def test_touch_targets_are_at_least_44px():
    body = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    last: dict[str, str] = {}
    for selectors, block in re.findall(r"([^{}]+)\{([^{}]*)\}", body):
        height = re.search(r"min-height:\s*([^;]+)", block)
        if height:
            for selector in selectors.split(","):
                last[" ".join(selector.split())] = height.group(1).strip()
    for selector in ("button", "select", 'input[type="number"]', 'input[type="text"]', 'input[type="date"]',
                     "button.chip", ".check", "nav.steps li"):
        assert last.get(selector) == "44px", selector
