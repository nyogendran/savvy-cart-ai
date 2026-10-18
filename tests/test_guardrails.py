"""Grounding guardrails as ADK callbacks: window enforcement, number accumulation, ungrounded-number stripping (SC-023)."""

from __future__ import annotations

from google.adk.models import LlmResponse
from google.genai import types

from savvycart import agent, guardrails


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _Ctx:
    def __init__(self, state: dict) -> None:
        self.state = state


WINDOW = {"window_start": "2026-10-22", "window_end": "2026-10-29"}


def test_before_tool_guard_keeps_the_agent_inside_the_planning_window():
    ctx = _Ctx(dict(WINDOW))
    assert guardrails.before_tool_guard(_Tool("plan_day"), {"day": "2026-10-24"}, ctx) is None
    for name in ("plan_day", "check_card_offer"):
        refused = guardrails.before_tool_guard(_Tool(name), {"day": "2026-11-15"}, ctx)
        assert refused and "outside" in refused["error"]
    assert guardrails.before_tool_guard(_Tool("get_pantry"), {"today": "2026-11-01"}, ctx)["error"]
    assert guardrails.before_tool_guard(_Tool("get_pantry"), {"today": "2026-10-22"}, ctx) is None
    # With no window seeded, nothing is blocked.
    assert guardrails.before_tool_guard(_Tool("plan_day"), {"day": "2027-01-01"}, _Ctx({})) is None


def test_after_tool_guard_allows_engine_numbers_but_not_echoed_arguments_or_out_of_window_results():
    ctx = _Ctx({**WINDOW, "allowed": []})
    guardrails.after_tool_guard(_Tool("plan_day"), {}, ctx,
                                {"day": {"date": "2026-10-24"}, "effective_cost_lkr": 4609, "qty": 99})
    assert "4609" in ctx.state["allowed"] and "99" not in ctx.state["allowed"]  # qty is an echoed field
    # A result dated outside the window contributes nothing.
    ctx2 = _Ctx({**WINDOW, "allowed": []})
    guardrails.after_tool_guard(_Tool("plan_day"), {}, ctx2, {"day": {"date": "2026-12-25"}, "effective_cost_lkr": 7777})
    assert ctx2.state["allowed"] == []
    # An error result contributes nothing.
    ctx3 = _Ctx({**WINDOW, "allowed": []})
    guardrails.after_tool_guard(_Tool("plan_day"), {}, ctx3, {"error": "bad"})
    assert ctx3.state["allowed"] == []


def _response(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def test_after_model_guard_strips_ungrounded_numbers_and_swapped_roles():
    ctx = _Ctx({"allowed": ["4609", "1331", "2026", "10", "23"], "total": 4609, "saving": 1331})
    out = guardrails.after_model_guard(ctx, _response("Plan total 4609 LKR, saving 1331 LKR. A single store costs 99999 LKR."))
    text = out.content.parts[0].text
    assert "99999" not in text and "4609" in text and "1331" in text
    swapped = guardrails.after_model_guard(ctx, _response("You save 4609 LKR. Cargills is cheaper on Friday."))
    assert "save 4609" not in swapped.content.parts[0].text and "Cargills is cheaper on Friday." in swapped.content.parts[0].text
    # Clean text is left untouched (callback returns None).
    assert guardrails.after_model_guard(ctx, _response("Plan total 4609 LKR, saving 1331 LKR.")) is None
    # A tool-call response (no text part) is left untouched.
    fc = LlmResponse(content=types.Content(role="model", parts=[types.Part.from_function_call(name="plan_day", args={})]))
    assert guardrails.after_model_guard(ctx, fc) is None


def test_session_state_seeds_allowed_numbers_and_roles():
    context = {"engine_plan": {"effective_cost_lkr": 4609, "saving_vs_usual_lkr": 1331}, "window": {}}
    state = guardrails.session_state(context, "2026-10-22", "2026-10-29")
    assert state["total"] == 4609 and state["saving"] == 1331
    assert "4609" in state["allowed"] and state["window_start"] == "2026-10-22"


def test_build_agent_wires_all_three_callbacks_and_the_offer_tool():
    built = agent.build_agent("")
    assert built.before_tool_callback is guardrails.before_tool_guard
    assert built.after_tool_callback is guardrails.after_tool_guard
    assert built.after_model_callback is guardrails.after_model_guard
    tool_names = {getattr(t, "__name__", getattr(t, "name", "")) for t in built.tools}
    assert "check_card_offer" in tool_names and "plan_day" in tool_names


def test_offer_terms_must_be_stated_by_the_shopper():
    stated = guardrails.numbers_in_text("Seylan gives 10% off on Saturday, minimum Rs. 8,000 and up to Rs 1,000 off")
    assert {10.0, 8000.0, 1000.0} <= stated
    ctx = _Ctx({**WINDOW, "stated": sorted(stated), "allowed": []})
    ok = {"day": "2026-10-24", "percent_off": 10, "min_bill_lkr": 8000, "max_discount_lkr": 1000}
    assert guardrails.before_tool_guard(_Tool("check_card_offer"), ok, ctx) is None
    assert guardrails.before_tool_guard(_Tool("check_card_offer"), {**ok, "max_discount_lkr": None}, ctx) is None
    for invented in ({**ok, "min_bill_lkr": 102852}, {**ok, "percent_off": 25}, {**ok, "max_discount_lkr": True}):
        assert "stated" in guardrails.before_tool_guard(_Tool("check_card_offer"), invented, ctx)["error"]
    steered = {"day": "2026-10-24", "gap_lkr": 98765, "terms_pay_lkr": 0,
               "terms_used": {"percent_off": 10, "min_bill_lkr": 102852, "max_discount_lkr": 1000}}
    guardrails.after_tool_guard(_Tool("check_card_offer"), {}, ctx, steered)
    assert "98765" not in ctx.state["allowed"]
    fair = {**steered, "gap_lkr": 2468, "terms_used": {"percent_off": 10, "min_bill_lkr": 8000, "max_discount_lkr": 1000}}
    guardrails.after_tool_guard(_Tool("check_card_offer"), {}, ctx, fair)
    assert "2468" in ctx.state["allowed"] and "8000" not in ctx.state["allowed"]  # terms_used is an echoed field


def test_ungrounded_numbers_take_their_currency_word_with_them():
    allowed = {"4609", "1331"}
    assert guardrails.strip_ungrounded("One store costs 99999 LKR. Plan total 4609 LKR.", allowed) == "One store costs. Plan total 4609 LKR."
    assert guardrails.strip_ungrounded("Pay LKR 99999 today.", allowed) == "Pay today."
    assert guardrails.strip_ungrounded("Prices are in LKR. You save 1331 in LKR.", allowed) == "Prices are in LKR. You save 1331 in LKR."
    assert guardrails.clean_text("Plan total 4,609 LKR, saving 1,331 LKR.", allowed, 4609, 1331) == "Plan total 4609 LKR, saving 1331 LKR."
    assert guardrails.clean_text("You save 4,609 LKR. Fine.", allowed | {"4", "609"}, 4609, 1331) == "Fine."
    assert guardrails.clean_text("One store costs 2,609 LKR.", allowed | {"2", "609"}, 4609, 1331) == "One store costs."


def test_page_never_grounds_a_number_from_unstated_offer_terms():
    from urllib.parse import urlencode

    from fastapi.testclient import TestClient

    from savvycart.http import app

    lines = [{"sku_id": "uht_milk_1l", "qty": 4}, {"sku_id": "carrot", "qty": 0.5}]
    eligible = agent.check_card_offer("Seylan Bank", "keells", 10, [], ["saturday"], lines, "2026-10-24")["eligible_lkr"]
    steered = agent.check_card_offer("Seylan Bank", "keells", 10, [], ["saturday"], lines, "2026-10-24", min_bill_lkr=eligible + 98765)
    assert steered["gap_lkr"] == 98765

    async def runner(question, context):
        return {"text": "Holding that card saves you 98765 LKR.", "calls": [{"name": "check_card_offer", "args": {}}],
                "results": [{"name": "check_card_offer", "response": steered}]}

    app.state.agent_runner = runner
    try:
        with TestClient(app) as http:
            page = http.post("/ui", content=urlencode([("action", "explain"), ("question", "Is a 10% Seylan offer worth it?")]),
                             headers={"content-type": "application/x-www-form-urlencoded"}).text
    finally:
        app.state.agent_runner = None
    assert "98765" not in page.split('id="explanation-text">')[1].split("</p>")[0]


def test_callbacks_run_inside_the_real_adk_loop():
    import asyncio
    from typing import AsyncGenerator

    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_request import LlmRequest

    class Scripted(BaseLlm):
        async def generate_content_async(self, req: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
            answered = any(p.function_response is not None for c in req.contents for p in (c.parts or []))
            if not answered:
                plan = {"lines": [{"sku_id": "carrot", "qty": 1}], "banks": ["HNB"], "max_stores": 1, "trip_cost_lkr": 250, "usual_store": "keells"}
                parts = [types.Part.from_function_call(name="plan_day", args={**plan, "day": "2026-12-25"}),
                         types.Part.from_function_call(name="plan_day", args={**plan, "day": "2026-10-24"}),
                         types.Part.from_function_call(name="check_card_offer", args={
                             "bank": "X", "store_id": "keells", "percent_off": 25, "excluded_items": [], "days": ["saturday"],
                             "lines": [{"sku_id": "carrot", "qty": 1}], "day": "2026-10-24"})]
            else:
                parts = [types.Part(text="Your total is 4609 LKR. You save 4609 LKR. One store costs 99999 LKR.")]
            yield LlmResponse(content=types.Content(role="model", parts=parts))

    context = {"engine_plan": {"effective_cost_lkr": 4609, "saving_vs_usual_lkr": 1331}, "window": {"start": "2026-10-22", "end": "2026-10-29"}}
    result = asyncio.run(agent.ask_agent("Is a 10% card offer worth it?", context, agent=agent.build_agent(Scripted(model="s"))))
    outcomes = [("error" in r["response"], r["name"]) for r in result["results"]]
    assert outcomes == [(True, "plan_day"), (False, "plan_day"), (True, "check_card_offer")]  # out of window; 25% was never stated
    assert result["text"] == "Your total is 4609 LKR. One store costs."


def _scripted(responses):
    """A scripted model for the real ADK loop: one list of parts per model turn."""
    from typing import AsyncGenerator

    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_request import LlmRequest

    class Scripted(BaseLlm):
        async def generate_content_async(self, req: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
            turn = sum(1 for c in req.contents if c.role == "model")
            yield LlmResponse(content=types.Content(role="model", parts=responses[min(turn, len(responses) - 1)]))

    return Scripted(model="scripted")


def _default_context():
    from savvycart import http

    state = http._parse_state({})
    items = http._pantry_view(state)
    plan, _ = http._engine_plan(state, items)
    lines = http._lines(items)
    return {"confirmed": http._confirmed(plan, state, lines), "engine_plan": plan, "window": {"start": "2026-10-22", "end": "2026-10-29"}}, lines


def test_comma_numbers_and_multi_part_answers_are_grounded_inside_the_agent():
    import asyncio

    context, _ = _default_context()
    comma = _scripted([[types.Part(text="You save 4,604 LKR. One store costs 2,609 LKR. Plan total 4,604 LKR, saving 1,328 LKR.")]])
    text = asyncio.run(agent.ask_agent("Explain", context, agent=agent.build_agent(comma)))["text"]
    assert text == "One store costs. Plan total 4604 LKR, saving 1328 LKR."
    split = _scripted([[types.Part(text="Thinking about 77777.", thought=True), types.Part(text="You save "),
                        types.Part(text="4604 LKR. Cargills is cheaper on Friday."), types.Part(text="One store costs 4"), types.Part(text="4 LKR.")]])
    text = asyncio.run(agent.ask_agent("Explain", context, agent=agent.build_agent(split)))["text"]
    assert "save" not in text and "77777" not in text and "44" not in text and "Cargills is cheaper on Friday." in text


def test_replans_may_only_use_the_shoppers_basket_trip_cost_and_stated_terms():
    import asyncio
    from urllib.parse import urlencode

    from fastapi.testclient import TestClient

    from savvycart.http import app

    context, lines = _default_context()
    steered = [{"sku_id": "cheese_250g", "qty": 50}, {"sku_id": "milk_powder_400g", "qty": 22.127}]
    offer = {"bank": "Seylan Bank", "store_id": "keells", "percent_off": 10, "excluded_items": [], "days": ["saturday"], "day": "2026-10-24"}
    trip = {k: v for k, v in context["confirmed"].items() if k != "day"}
    calls = [types.Part.from_function_call(name="check_card_offer", args={**offer, "lines": steered}),
             types.Part.from_function_call(name="plan_day", args={**trip, "day": "2026-10-24", "lines": steered}),
             types.Part.from_function_call(name="plan_day", args={**trip, "day": "2026-10-24", "trip_cost_lkr": 4321}),
             types.Part.from_function_call(name="check_card_offer", args={**offer, "lines": lines[:3]}),
             types.Part.from_function_call(name="plan_day", args={**trip, "day": "2026-10-24"})]
    model = _scripted([calls, [types.Part(text="Holding that card saves you 98765 LKR. A 4321 LKR trip is fine.")]])
    result = asyncio.run(agent.ask_agent("Is a 10% Seylan offer worth it?", context, agent=agent.build_agent(model)))
    assert [("error" in r["response"]) for r in result["results"]] == [True, True, True, False, False]
    assert "98765" not in result["text"] and "4321" not in result["text"]

    async def runner(question, ctx):
        return await agent.ask_agent(question, ctx, agent=agent.build_agent(_scripted([calls[:1], [types.Part(text="It saves you 98765 LKR.")]])))

    app.state.agent_runner = runner
    try:
        with TestClient(app) as http:
            page = http.post("/ui", content=urlencode([("action", "explain"), ("question", "Is a 10% Seylan offer worth it?")]),
                             headers={"content-type": "application/x-www-form-urlencoded"}).text
    finally:
        app.state.agent_runner = None
    assert "98765" not in page.split('id="explanation-text">')[1].split("</p>")[0]
    for bad in (-5, 0, float("nan"), float("inf"), 51):
        assert "error" in agent.check_card_offer("X", "keells", 10, [], ["saturday"], [{"sku_id": "cheese_250g", "qty": bad}], "2026-10-24")
