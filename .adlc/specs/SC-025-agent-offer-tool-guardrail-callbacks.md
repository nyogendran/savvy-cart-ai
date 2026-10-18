# SC-025 — v2.3: check_card_offer agent tool, guardrails as ADK callbacks, whole-pack quantities

Builds on the approved SC-023 spec. Every SC-023 rule stays unless it is listed under **Supersedes**. Prototype deadline 18 Oct 2026.

**Origin:** built on 18 Oct 2026 in a session after SC-024 was accepted, before gating; then reviewed. The review reproduced three defects in the new agent tool (an invented "saves you 98765 LKR" reached the page through model-chosen offer terms; an unknown cap or minimum was forced to a number; an offer was priced on a day it is not valid), which are fixed here. P1 approval is the human's recorded spec-approval gate; P6 stays with the human.

## Problem

1. The Offer Reality Check lives only on its own page; a shopper on the Why step cannot ask the agent whether an offer they describe is worth it.
2. Grounding runs only after the agent finishes, outside the ADK loop; the agent itself can still call tools outside the planning window and emit ungrounded numbers that are filtered later.
3. The pantry suggests fractions of packaged goods (2.5 packs of buns) because quantities are medians.

## Supersedes

| SC-023 rule | v2.3 rule |
| --- | --- |
| The agent has five tools | The agent also has `check_card_offer`, which prices an offer the shopper describes through the same reality check |
| Grounding runs only in the Why-step post-filter | The same rules also run inside the agent as ADK `before_tool`, `after_tool`, and `after_model` callbacks; the post-filter stays as an outer net |
| D7: the Seylan sample terms were captured on 17 Oct 2026 | The terms were first recorded on 17 Oct 2026; the headline "10% off on Total Bill" and every term were re-checked on the bank's page on 18 Oct 2026, so `captured_on` is 18 Oct |
| Pantry quantities are medians to 3 decimals | Items sold by weight (`unit: kg`) keep 3 decimals; items sold as units are whole numbers (median rounded half up, at least 1) |

## In scope

1. **`check_card_offer` agent tool.** Arguments: bank, store, percent, excluded items, valid days, basket lines, day, and optional minimum and cap. It validates through `offercheck.validate_rule`, refuses a day the offer is not valid on, and returns engine figures (headline suggests, terms pay, eligible subtotal, minimum met, gap, cap reached, you pay) plus the terms it used.
2. **Stated terms only.** The tool's figures are derived from the terms it is given, so its percent, minimum, and cap must each appear among the numbers in the shopper's own question. The `before_tool` callback refuses a call with any other term, and both the `after_tool` callback and the page's post-filter ignore its figures unless the terms were stated. The question's numbers never widen the set of numbers an answer may use.
3. **Guardrails as ADK callbacks** (`src/savvycart/guardrails.py`): `before_tool` refuses `plan_day` and `check_card_offer` outside the shopper's 7-day window and `get_pantry` for another day; `after_tool` adds only engine numbers (echoed fields excluded) to the allowed set; `after_model` strips ungrounded numbers and role-swapped sentences and tidies an orphaned "LKR". The Why-step post-filter applies the same rules again.
4. **Whole-pack quantities** in the pantry engine and the Pantry step (step 1 for units, any amount for kg, unit hints, aligned inputs).

## Out of scope

- Live Gemini verification (still required right after deploy; D1 applies).

## Acceptance criteria

1. Given a described offer, the agent tool prices it through the reality check, leaves an unstated minimum or cap out with a note, and refuses a day the offer is not valid on. **Verified by** `python -m pytest tests/test_offer_check.py::test_check_card_offer_agent_tool_grounds_in_the_engine_and_refuses_bad_input -q`.
2. Given offer terms the shopper did not state, the tool call is refused and its figures never ground a number, inside the agent and on the page. **Verified by** `python -m pytest tests/test_guardrails.py::test_offer_terms_must_be_stated_by_the_shopper tests/test_guardrails.py::test_page_never_grounds_a_number_from_unstated_offer_terms -q`.
3. Given a scripted model in the real ADK loop, an out-of-window tool call and an unstated-terms offer call are refused, and an invented number and a swapped sentence never leave the agent. **Verified by** `python -m pytest tests/test_guardrails.py::test_callbacks_run_inside_the_real_adk_loop -q`.
4. Given the guardrail functions, the window, accumulation, stripping, and unit-tidy rules hold. **Verified by** `python -m pytest tests/test_guardrails.py -q`.
5. Given the sample history, packaged items are whole numbers and weighed items keep fractions. **Verified by** `python -m pytest tests/test_v22_page.py -q`.
6. Every earlier test still passes and the default demo plan is unchanged (LKR 4,609, saving LKR 1,331). **Verified by** `python -m pytest -q`.
7. The README checker passes. **Verified by** `python scripts/check_judge_readme.py`.

## Approved assumptions

| Id | Assumption |
| --- | --- |
| E1 | An offer term counts as stated when the same number appears in the shopper's question (thousands separators ignored). |
| E2 | The callbacks are verified with a scripted model in the real ADK loop; live Gemini is still verified after deploy (D1). |
| E3 | The changes touch `agent.py`, frozen by the open deploy ticket SC-012, so P5 uses a signed cross-model review by Gemini. |
| E4 | Cut-off 17:00 Colombo on 18 Oct 2026; if v2.3 is not accepted by then, v2.2 (main) is deployed. |
| E5 | A typed fractional amount for an item sold as units is rounded up to the next whole unit; the input accepts whole numbers only. |
