"""Grounding guardrails, shared by the Why-step post-filter and the ADK agent's own callbacks.

Two layers enforce the same rules:
  - Inside the agent: ADK before_tool / after_tool / after_model callbacks keep the model within the
    planning window and strip ungrounded numbers before a response leaves the model.
  - On the way to the page: _explain_v2 applies the same functions again, which also covers the
    fallback and test paths that do not run the real ADK agent.
"""

from __future__ import annotations

import re
from typing import Any

from savvycart.explain import numbers_in_plan

# Engine tools whose numeric results an explanation may quote. explain_plan_numbers only echoes a
# plan the model supplies, so it cannot widen the filter and is left out.
GROUNDING_TOOLS = ("get_pantry", "load_catalog", "load_offers", "plan_day", "check_card_offer")

# Fields that echo or derive from model-chosen tool arguments rather than engine data.
ECHOED_FIELDS = {
    "plan_day": {"qty", "trip_cost_lkr", "max_stores", "unpriced", "missing"},
    "get_pantry": {"today", "days_left", "reason"},
    "check_card_offer": {"qty", "day", "notes", "terms_used", "lines_used"},
}
# check_card_offer prices terms the model passes in, so its figures are only as good as those terms: they count as
# grounded only when every term number (percent, minimum, cap) was stated by the shopper in their own question.
TERM_FIELDS = ("percent_off", "min_bill_lkr", "max_discount_lkr")


def numbers_in_text(text: str) -> set[float]:
    """Every number the shopper wrote, with thousands separators removed ("Rs. 8,000" -> 8000.0, "10%" -> 10.0)."""
    plain = re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(text or ""))
    return {float(n) for n in re.findall(r"\d+(?:\.\d+)?", plain)}


def terms_stated(terms: Any, stated: set[float]) -> bool:
    """True when every term number the tool was given appears in the shopper's own words."""
    if not isinstance(terms, dict):
        return False
    for field in TERM_FIELDS:
        value = terms.get(field)
        if value is None:
            continue
        try:
            if isinstance(value, bool) or float(value) not in stated:
                return False
        except (TypeError, ValueError):
            return False
    return True


CURRENCY_WORDS = {"lkr", "rs", "rupees"}


def normalize_numbers(text: str) -> str:
    """'4,609' -> '4609' and '4609.00' -> '4609', so every check sees the number the engine produced."""
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(text or ""))
    return re.sub(r"(?<=\d)\.00\b", "", text)


def strip_ungrounded(text: str, allowed: set[str]) -> str:
    """Drop every word carrying a number the engine did not produce, and the currency word beside it
    ("costs 99999 LKR." -> "costs."), keeping sentence-ending punctuation."""
    tokens = text.split()
    drop = {i for i, t in enumerate(tokens) if any(n not in allowed for n in re.findall(r"\d+", t))}
    for i in sorted(drop):
        for j in (i - 1, i + 1):
            if 0 <= j < len(tokens) and re.sub(r"[^\w]", "", tokens[j]).lower() in CURRENCY_WORDS and not re.search(r"\d", tokens[j]):
                drop.add(j)
    kept: list[str] = []
    for i, token in enumerate(tokens):
        if i not in drop:
            kept.append(token)
            continue
        ending = re.search(r"[.!?]+$", token)
        if ending and kept and not re.search(r"[.!?]$", kept[-1]):
            kept[-1] += ending.group(0)
    return " ".join(kept).strip()


def clean_text(text: str, allowed: set[str], total: int, saving: int) -> str:
    """The full grounding pass applied to any text a shopper will read."""
    return drop_swapped_roles(strip_ungrounded(normalize_numbers(text), allowed), total, saving)


def basket_of(lines: Any) -> dict[str, float] | None:
    """{sku_id: total qty} for well-formed lines, or None when the lines are not a list of {sku_id, qty}."""
    if not isinstance(lines, list) or not lines:
        return None
    basket: dict[str, float] = {}
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("sku_id"), str):
            return None
        qty = line.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)):
            return None
        basket[line["sku_id"]] = basket.get(line["sku_id"], 0.0) + float(qty)
    return basket


def lines_within_basket(lines: Any, basket: dict[str, float]) -> bool:
    """A re-plan may leave items out of the shopper's basket but may not add items or change quantities."""
    asked = basket_of(lines)
    return asked is not None and all(sku in basket and abs(qty - basket[sku]) < 1e-6 for sku, qty in asked.items())


def trip_cost_allowed(value: Any, confirmed: Any, stated: set[float]) -> bool:
    if value is None or isinstance(value, bool):
        return value is None
    try:
        return float(value) == float(confirmed) or float(value) in stated
    except (TypeError, ValueError):
        return False

# Tools whose result or argument carries a day that must fall inside the planning window.
DAY_BOUNDED = ("plan_day", "check_card_offer")

SAVING_WORDS = re.compile(r"^(save|saves|saved|saving|savings|discount)$")
TOTAL_WORDS = re.compile(r"^(pay|pays|paid|paying|total|cost|costs|spend|spending|bill)$")
# A colon stays inside its clause ("Plan total: 4609 LKR"); parentheses start a new one.
CLAUSE_BREAK = re.compile(r"[,;()—]|\b(?:and|but|while|whereas)\b")
ROLE_WINDOW = 5


def grounding_view(name: str, response: Any) -> Any:
    """An engine tool result without the fields that echo model-chosen arguments."""
    drop = ECHOED_FIELDS.get(name, set())
    if isinstance(response, dict):
        return {k: grounding_view(name, v) for k, v in response.items() if k not in drop}
    if isinstance(response, list):
        return [grounding_view(name, v) for v in response]
    return response


def _number_role(words: list[str], i: int) -> str | None:
    """'saving' or 'total' from the nearest role word on either side, or None when absent or tied."""
    found = []
    for j, word in enumerate(words):
        if j == i or abs(j - i) > ROLE_WINDOW:
            continue
        if SAVING_WORDS.match(word):
            found.append((abs(j - i), "saving"))
        elif TOTAL_WORDS.match(word):
            found.append((abs(j - i), "total"))
    if not found:
        return None
    nearest = min(d for d, _ in found)
    roles = {role for d, role in found if d == nearest}
    return roles.pop() if len(roles) == 1 else None


def drop_swapped_roles(text: str, total: int, saving: int) -> str:
    """Drop a sentence that calls the plan total a saving, or the saving a total (numbers alone cannot tell)."""
    if total == saving:
        return text
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        swapped = False
        for clause in CLAUSE_BREAK.split(sentence):
            words = [re.sub(r"[^\w]", "", w).lower() for w in (clause or "").split()]
            for i, word in enumerate(words):
                role = _number_role(words, i) if word in (str(total), str(saving)) else None
                if (word == str(total) and role == "saving") or (word == str(saving) and role == "total"):
                    swapped = True
        if not swapped:
            kept.append(sentence)
    return " ".join(kept).strip()


def inputs_problem(name: str, args: Any, basket: dict[str, float], trip_cost: Any, stated: set[float]) -> str | None:
    """Why a re-planning tool's inputs are not the shopper's (None when they are). Shared by both guard layers."""
    if name not in ("plan_day", "check_card_offer") or not basket or not isinstance(args, dict):
        return None
    if (name == "check_card_offer" or "lines" in args) and not lines_within_basket(args.get("lines"), basket):
        return "Use the shopper's basket: you may leave items out, but not add items or change quantities."
    if name == "plan_day" and "trip_cost_lkr" in args and not trip_cost_allowed(args.get("trip_cost_lkr"), trip_cost, stated):
        return "Use the shopper's trip cost, or one the shopper stated."
    if name == "check_card_offer" and (args.get("percent_off") is None or not terms_stated(args, stated)):
        return "Use only the percent, minimum, and cap the shopper stated; leave out a term they did not state."
    return None


def result_inputs(name: str, response: dict[str, Any]) -> dict[str, Any]:
    """The inputs an engine result was computed from, as the result itself reports them."""
    # Only what the result carries is checked; a real plan_day result always carries its bills and trip cost.
    found: dict[str, Any] = {}
    if name == "plan_day":
        if isinstance(response.get("stores"), list):
            found["lines"] = [{"sku_id": l.get("sku_id"), "qty": l.get("qty")} for b in response["stores"] if isinstance(b, dict)
                              for l in b.get("lines", []) if isinstance(l, dict)]
        if "trip_cost_lkr" in response:
            found["trip_cost_lkr"] = response["trip_cost_lkr"]
    elif name == "check_card_offer":
        found = {"lines": response.get("lines_used"), **(response.get("terms_used") or {})}
    return found


# --- ADK callbacks: the same rules, enforced inside the agent's own tool loop ---

def session_state(context: dict[str, Any], window_start: str, window_end: str, question: str = "") -> dict[str, Any]:
    """Initial agent-session state: the numbers an answer may use, the roles to protect, the day window, the shopper's
    basket and trip cost, and the numbers the shopper stated (the only new terms a re-plan may use)."""
    plan = context.get("engine_plan", {}) if isinstance(context, dict) else {}
    confirmed = context.get("confirmed", {}) if isinstance(context, dict) else {}
    return {
        "allowed": sorted(numbers_in_plan(context)),
        "total": plan.get("effective_cost_lkr", 0),
        "saving": plan.get("saving_vs_usual_lkr", 0),
        "window_start": window_start or "",
        "window_end": window_end or "",
        "stated": sorted(numbers_in_text(question)),
        "basket": basket_of(confirmed.get("lines")) or {},
        "trip_cost": confirmed.get("trip_cost_lkr"),
    }


def before_tool_guard(tool: Any, args: dict[str, Any], tool_context: Any) -> dict[str, Any] | None:
    """Refuse a tool call that would leave the shopper's planning window or change the shopper's inputs."""
    name = getattr(tool, "name", "")
    state = tool_context.state
    start, end = state.get("window_start"), state.get("window_end")
    if not start:
        return None
    if name in DAY_BOUNDED:
        day = str(args.get("day", ""))
        if day and not start <= day <= end:
            return {"error": f"Plan only for a day from {start} to {end}; {day} is outside the shopper's window."}
    if name == "get_pantry" and str(args.get("today", "")) not in ("", start):
        return {"error": f"Use today = {start}, the shopper's planning day."}
    problem = inputs_problem(name, args, state.get("basket") or {}, state.get("trip_cost"), set(state.get("stated", [])))
    if problem is None and name == "check_card_offer" and (args.get("percent_off") is None
                                                           or not terms_stated(args, set(state.get("stated", [])))):
        problem = "Use only the percent, minimum, and cap the shopper stated; leave out a term they did not state."
    return {"error": problem} if problem else None


def result_grounds(name: str, response: Any, state: dict[str, Any]) -> bool:
    """Whether an engine result may widen the numbers an answer can quote (the page's post-filter uses this too)."""
    if name not in GROUNDING_TOOLS or not isinstance(response, dict) or "error" in response:
        return False
    start, end = state.get("window_start"), state.get("window_end")
    if name in DAY_BOUNDED:
        planned = response.get("day")
        day = str(planned.get("date", "")) if isinstance(planned, dict) else str(planned or "")
        if start and not (day and start <= day <= end):
            return False
    if name == "get_pantry" and start and response.get("today") != start:
        return False
    stated = set(state.get("stated", []))
    if name == "check_card_offer" and not terms_stated(response.get("terms_used"), stated):
        return False
    return inputs_problem(name, result_inputs(name, response), state.get("basket") or {}, state.get("trip_cost"), stated) is None


def after_tool_guard(tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any) -> dict[str, Any] | None:
    """Add the engine numbers this result produced to the set an answer may quote. Never changes the result."""
    name = getattr(tool, "name", "")
    if result_grounds(name, tool_response, tool_context.state):
        allowed = set(tool_context.state.get("allowed", []))
        allowed |= numbers_in_plan(grounding_view(name, tool_response))
        tool_context.state["allowed"] = sorted(allowed)
    return None


def answer_text(parts: Any) -> str:
    """The shopper-facing text of a model response: text parts joined with spaces; thought parts left out."""
    return " ".join(p.text for p in parts or [] if getattr(p, "text", None) and not getattr(p, "thought", False)).strip()


def after_model_guard(callback_context: Any, llm_response: Any) -> Any:
    """Ground the whole answer text before it leaves the model; function calls and thought parts pass unchanged."""
    from google.genai import types

    content = getattr(llm_response, "content", None)
    parts = list(getattr(content, "parts", None) or [])
    text_parts = [p for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)]
    if not text_parts:
        return None
    state = callback_context.state
    original = answer_text(parts)
    cleaned = clean_text(original, set(state.get("allowed", [])), state.get("total", 0), state.get("saving", 0))
    if cleaned == original and len(text_parts) == 1:
        return None
    first = parts.index(text_parts[0])
    new_parts = [p for p in parts if p not in text_parts]
    new_parts.insert(min(first, len(new_parts)), types.Part(text=cleaned))
    return llm_response.model_copy(update={"content": types.Content(role=content.role, parts=new_parts)})
