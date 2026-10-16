"""Plan explanation bound to optimizer JSON numbers only."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

NUMBER_RE = re.compile(r"\d+")

EXPLAIN_INSTRUCTION = (
    "Write a short shopper-facing explanation of this plan JSON. "
    "Every number in your text must already appear in the JSON. "
    "Do not invent prices, discounts, or totals."
)


class ExplainModelClient(Protocol):
    def explain(self, plan_json: dict[str, Any], instruction: str) -> str: ...


def numbers_in_plan(plan: dict[str, Any]) -> set[str]:
    """Collect digit sequences present anywhere in the plan JSON."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, int):
            found.add(str(value))
            return
        if isinstance(value, float):
            if value.is_integer():
                found.add(str(int(value)))
            else:
                found.update(NUMBER_RE.findall(str(value)))
            return
        if isinstance(value, str):
            found.update(NUMBER_RE.findall(value))
            return
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
            return
        if isinstance(value, list):
            for child in value:
                walk(child)

    walk(plan)
    return found


def drop_unallowed_number_tokens(text: str, allowed: set[str]) -> str:
    """Drop whitespace tokens that introduce a number absent from the plan."""
    kept: list[str] = []
    for token in text.split():
        nums = NUMBER_RE.findall(token)
        if nums and any(n not in allowed for n in nums):
            continue
        kept.append(token)
    return " ".join(kept).strip()


def ensure_discount_sentence(text: str, discount: int) -> str:
    digits = str(discount)
    if digits in text:
        return text
    sentence = f"Legal saving: {discount} LKR."
    if not text:
        return sentence
    return f"{text} {sentence}"


def explain_plan(
    plan: dict[str, Any],
    *,
    model_client: ExplainModelClient,
) -> dict[str, Any]:
    """Ask the model for text, then strip invented numbers and ensure discount."""
    raw = model_client.explain(plan, EXPLAIN_INSTRUCTION)
    allowed = numbers_in_plan(plan)
    cleaned = drop_unallowed_number_tokens(raw, allowed)
    discount = int(plan["discount"])
    text = ensure_discount_sentence(cleaned, discount)
    cited_fields = ["discount"]
    return {"text": text, "cited_fields": cited_fields, "plan": plan}


def plan_json_for_model(plan: dict[str, Any]) -> str:
    return json.dumps(plan, sort_keys=True)
