# SC-032 — v2.6: truthful category offers, responsive Gemini steps, a mock cart, plan with a checked card, leaner calls

**Status:** READY_FOR_APPROVAL (revision 2; revision 1 approved) · **Ticket:** SC-032 (spec) · build ticket SC-033

Builds on SC-030 (revision 4). Every earlier rule stays unless it is listed under **Supersedes**. Prototype deadline 18 Oct 2026; SC-025's 17:00 Colombo deploy cut-off applies.

**Origin:** the human ran the live site on 18 Oct 2026 with a real SMS offer ("Save 25% at Keells on Fresh Meat, Fruits & Vegetables with Mastercard Credit Cards every Sunday till 31 Oct, for bills above LKR 5,000 & max savings LKR 1,500. T&C Apply.") and asked for a UX-gap review, a cart at Approve, and an API-call review. All five resulting items were chosen, in this order.

## Problem (measured on the live site)

1. **Untrue payout.** The offer schema records only excluded items, so a category-limited offer is priced on the whole bill: the SMS shows "pays LKR 1,381 … every item counts" (dish wash bar, bread, and milk marked "Counts"); limited to fresh items it pays about LKR 407. "Till 31 Oct" reads as "No end date could be read". "Combines with store promotions: yes" is shown although the SMS does not say. "Mastercard" is a card network, not a bank, and nothing says so.
2. **Slow steps with no feedback.** Read it with Gemini took 9 to 41 s, Next: explain this plan 60.2 s and then "The agent call failed" (60 s limit), Ask 37 s. No spinner; buttons stay clickable (double submits). Agent answers show raw Markdown (`**`, `###`, `*`). Re-plan notices use parameter names ("max_stores 1 instead of 2"). Refreshing the Why step runs the agent again.
3. **Approve is not actionable.** The button is "Update"; the result is a "MOCK preview id"; there is no per-store list.
4. **Dead end after an offer check.** It says holding the card would cost less on its day, but there is no way to plan with it.
5. **Repeated work.** Every step recomputes the day sweep, the plan, and up to about 15 suggestion re-plans; Approve calls this app's own `/v1/approve` over HTTP; the stylesheet URL has no version, so a deploy can serve stale CSS.

## Supersedes

| Earlier rule | v2.6 rule |
| --- | --- |
| Offers record exclusions only; `include_categories` is always empty for a checked offer | The schema adds `applies_only_to`; terms map to catalog categories; items outside them do not count |
| `valid_until` must be ISO | A day and month without a year (for example "31 Oct") reads as the next such date on or after the planning date |
| An unstated "combines with store promotions" is shown as "yes" | Shown as "yes (not stated in the offer)", and the confirm form keeps it unstated unless the shopper changes it |
| Plan's "Next: explain this plan" runs the agent (action `explain`) | It opens the Why step with the engine explanation at once (action `why`); the agent runs only on Ask or a sample question (action `explain`, unchanged) |
| `AGENT_TIMEOUT_SECONDS = 60` | 100 (Cloud Run's request timeout is 120) |
| Notices name parameters (`max_stores`, `trip_cost_lkr`, `usual_store`) | Plain words: "at most 1 store instead of 2", "extra trip cost LKR 300 instead of LKR 250", "usual store Cargills instead of Keells"; "day … instead of …", cards, and "a different basket" are unchanged |
| Approve shows a recap, fees, and a MOCK preview id with an "Update" button | Approve shows a MOCK cart per store plus Copy and Share actions; the button is "Update my cart"; the delivery fee list, "MOCK", and "No order is sent." stay |
| `tests/test_v25_page.py` asserts the notice "max_stores 5 instead of 2" | It asserts "at most 5 stores instead of 2" |
| Revision 2 (P5 round 1) | The confirm form keeps "nothing in this catalog counts" as a ticked option, so an unmatched category never widens to the whole bill; an explicit printed year is honoured and only day-month patterns are read; the network note fires only for a bare network name; a term that maps to two categories adds an untick note; a cached answer still counts toward the per-minute cap (the earlier rate-limit test pins that order); the checked offer's terms are part of the answer-cache key; the household's sweep window is unchanged and the checked offer's own next day is an extra, labelled day choice ("the checked offer's day, after the estimated next purchase date"); the unused-offer notice names its reason (ended, wrong day, store not in the plan, or no bill costs less); "Plan with this card" with invalid terms says why; the printed groups of a "nothing in this catalog" offer survive rechecks and the carry; the cart's delivery total equals "Total with delivery" (plan total, including its trip estimate, plus fees); only single-day plans proven OPTIMAL are cached (sweeps report no solver status, so they are not cached); the checked offer's day stays a labelled choice after picking another day; the held-offer notice names the card and store; the "nothing in this catalog" marker is internal, so a model's literal "none" is an unmatched term with its note; bullets start only at the start or after a sentence |

## In scope

### A. Truthful category offers (`src/savvycart/offercheck.py`, `src/savvycart/http.py`)

1. `OFFER_SCHEMA` adds `"applies_only_to": array of strings`; `OFFER_PROMPT` adds: "If the discount applies only to some product groups, copy them as printed into applies_only_to; leave it empty when it applies to the whole bill. Give valid_until as printed if no year is shown."
2. `validate_rule(raw, catalog, source, today=None)` maps each `applies_only_to` term to catalog categories with a fixed word table: fresh ← fresh, meat, fish, seafood, chicken, fruit, fruits, vegetable, vegetables, veg, produce; staple ← staple, staples, grocery, groceries, dairy, bakery, bread, rice, dhal, flour, sugar, oil; household ← household, cleaning, detergent, soap, toiletries; a catalog category name maps to itself. The rule gains `include_categories` (sorted). A term that maps to two categories adds "“{term}” was read as {a} and {b} items; untick what does not apply." A term that maps to nothing adds the note "“{term}” matches no category in this catalog, so items under it are not counted." If terms were given and none maps, `include_categories` is `["none"]` (nothing counts) with that note. `planner_offer` passes `include_categories` through.
3. `reality_check` marks an item outside `include_categories` as not counting, with why "Not covered: the offer is for {categories} only".
4. End dates: ISO stays; "31 Oct", "31 October", "Oct 31", and "31/10" read as day and month; the year is the planning date's year, or the next year if that date is before the planning date. Note: "End date read as {ISO}." `today` defaults to the current date when not given (the agent's tool path).
5. When `combines_with_store_offers` is null, the rule keeps `stacks_with_promotions: true` and gains `stacks_stated: false`; the fact reads "yes (not stated in the offer)" and a note says "The terms do not say whether it combines with store promotions; checked as if it does."
6. When the bank text names only a card network (Visa, Mastercard, American Express, Amex, UnionPay), a note says "{network} is a card network, not a bank: the offer is for any {network} card of the kind named. Check which of your cards it is."
7. The confirm form adds "Only these count" checkboxes (Fresh, Staple, Household) as `o_incl`, carries `o_stack_unstated` while the combine checkbox is untouched, and `_form_rule` passes both through `validate_rule` with the planning date.

### B. Responsive Gemini steps (`src/savvycart/http.py`, `src/savvycart/static/app.css`)

1. A small script in the layout: on submit it blocks a second submit, then disables every button (after the browser has read the clicked one), and for `offer_read`, `explain`, a sample question, or `upload` shows a visible `#busy` status ("Gemini is reading the offer…", "The agent is working on your question…", "Gemini is reading your receipt…", each "This can take up to a minute."). `pageshow` from the back-forward cache re-enables the page.
2. Plan's "Next: explain this plan" and the Why step pill use action `why`: the Why step renders the engine explanation at once with source "Engine explanation. Ask the agent below for Gemini's view; it can take up to a minute." Action `explain` (Ask, Enter, a sample question) runs the agent as before.
3. Successful agent answers are cached per process for 15 minutes (at most 64) by a hash of the question and the agent's context; a cached answer is reused on refresh or return (it still counts toward the per-minute cap).
4. `AGENT_TIMEOUT_SECONDS = 100`.
5. The agent context gains `"answer_style": "Plain sentences, no Markdown, at most 120 words."`; the page renders any remaining `**bold**` as `<strong>`, `` `code` `` as `<code>`, removes `#` heading marks, and starts `* ` or `- ` bullets on a new line with "•", all inside the escaped `<p id="explanation-text">`.
6. Plain-language re-plan wording as in Supersedes.

### C. Mock cart at Approve (`src/savvycart/http.py`, `src/savvycart/static/app.css`)

1. One cart per bill: store, the card to pay with (or "No card offer applies"), each item with quantity (and "kg"), unit price, and amount after store promotions, then card discount and bill total; for Delivery, the store's assumed delivery fee and the store total.
2. A grand total. Pickup: the sum of the bills, with "plus LKR {n} for the extra trip, your estimate". Delivery: the plan total plus each store's fee, equal to "Total with delivery", with "(includes the LKR {n} extra-trip estimate from your plan)".
3. "Copy list" (`navigator.clipboard`) and "Share on WhatsApp" (`https://wa.me/?text=` with the escaped list) act on a plain-text list of the cart; no data leaves the page otherwise.
4. The MOCK preview id shows as "Cart reference (MOCK): {id}". "No order is sent. Savvy Cart does not contact any store or bank." and the delivery fee list stay; the button is "Update my cart".

### D. Plan with a checked card (`src/savvycart/http.py`, `src/savvycart/agent.py`)

1. After an offer check with a valid day, the result shows "Plan with this card on {Weekday} {d Mon}" (action `offer_plan`). It re-reads the confirmed terms from the form, sets the plan day to the offer's next valid day, and opens the Plan step.
2. The checked offer travels in a hidden `held_offer` field (JSON of the confirmed terms), is validated again on every request, and is held under the key "Checked offer ({bank})" so it never unlocks that bank's other offers.
3. The Plan, Why, and Approve steps price with it: bills say "Pay with {card products} (the offer you checked)"; the recommendation names it the same way; a notice says "This plan uses the offer you checked, with the terms as you confirmed them; the bank has not confirmed them." (or, when no bill uses it, "The offer you checked is not used: …" with the reason) with a "Remove the checked offer" button (action `drop_offer`).
4. The agent sees it: `build_agent`/`ask_agent` accept `extra_offers`; the agent's `load_offers` and `plan_day` include them.

### E. Leaner calls (`src/savvycart/http.py`)

1. Single-day plans proven OPTIMAL are cached per process by their inputs (basket, day, cards, stores, trip cost, usual store, checked offer), at most 256 entries; day sweeps carry no solver status and are recomputed.
2. Approve calls `approve_plan` directly instead of over HTTP.
3. The stylesheet link is `/static/app.css?v={first 10 hex of its SHA-256}`.

## Out of scope

- Real orders, logins, payments, or any store or bank integration.
- Streaming answers; background jobs; a database.
- Network-level card types in the wallet (the wallet stays issuer-only).

## Acceptance criteria

1. Given the SMS text read into `{"applies_only_to": ["Fresh Meat", "Fruits", "Vegetables"], …}` by a scripted model, the result says it pays the fresh-only amount, marks Dish wash bar, Sandwich bread, and milk "Not covered", and its rule has `include_categories == ["fresh"]`; a term like "Electronics" adds the no-category note; the SMS end date reads as 2026-10-31 with planning date 22 Oct 2026; an unstated combine shows "yes (not stated in the offer)"; "Mastercard" adds the network note. **Verified by** `python -m pytest tests/test_v26_page.py::test_category_limited_offer_pays_only_covered_items tests/test_v26_page.py::test_offer_end_dates_networks_and_unstated_terms -q`.
2. Given any page, the layout script blocks a second submit, disables buttons after submit, and shows `#busy` text for the slow actions; Plan's Next and the Why pill use `value="why"`; the Why step from `why` shows the engine explanation without calling the agent runner; `explain` calls it once and a repeat within 15 minutes does not; `AGENT_TIMEOUT_SECONDS == 100`; Markdown marks render as described; notices use the plain wording. **Verified by** `python -m pytest tests/test_v26_page.py::test_why_opens_instantly_and_the_agent_runs_on_ask tests/test_v26_page.py::test_busy_script_and_plain_answers -q`.
3. Given the default plan at Approve, each bill appears as a cart with its items, unit prices, amounts, card, and total; Delivery adds each store's fee and the grand total equals bills plus fees; Pickup states the extra-trip cost; Copy and Share act on the plain list; the button is "Update my cart"; "MOCK" and "No order is sent." remain. **Verified by** `python -m pytest tests/test_v26_page.py::test_approve_shows_a_mock_cart_per_store -q`.
4. Given an offer check whose held plan is cheaper, "Plan with this card on …" opens the Plan step for that day with a bill paying with the checked card and the notice; Why and Approve keep it; "Remove the checked offer" removes it; the checked key never unlocks other offers of the same bank; a scripted agent's `plan_day` with the checked key succeeds. **Verified by** `python -m pytest tests/test_v26_page.py::test_plan_with_a_checked_card -q`.
5. Given two identical Plan requests, the single-day plan is computed once (cache hit) and the sweep twice; Approve does not call `_internal_post`; the stylesheet URL carries `?v=` with the file hash. **Verified by** `python -m pytest tests/test_v26_page.py::test_engine_cache_direct_approve_and_versioned_css -q`.
6. Given the live deploy, the SMS reads with a fresh-only payout, Next: explain this plan opens in under 2 s, and an Ask answer arrives within 100 s. **Verified by** `python scripts/live_e2e_check.py https://savvy-cart-23322909520.asia-southeast1.run.app`, which posts the journey and prints each step's timing and checks; its output is recorded in `.adlc/evidence/SC-033-p6/`.
7. Every test passes, with only the superseded assertion changed in `tests/test_v25_page.py`. **Verified by** `python -m pytest -q` and `python scripts/check_judge_readme.py`.

## Approved assumptions

| Id | Assumption |
| --- | --- |
| H1 | The category word table is a fixed demo mapping onto this catalog's three categories; unknown terms count nothing and say so. |
| H2 | A cached agent answer is per instance and per exact question and context; a new question or a changed plan runs the agent again. |
| H3 | The cart is a MOCK list for the shopper to take to the store; nothing is sent anywhere except what the shopper chooses to copy or share. |
| H4 | A checked offer's terms are the shopper's confirmation, not the bank's; every page that uses it says so. |
| H5 | `agent.py` changes only to accept `extra_offers`; its tools and guardrails are otherwise unchanged. |
| H6 | Cut-off: if v2.6 is not accepted by 17:00 Colombo, v2.5 stays deployed. |
| H7 | Revision 2's changes come from P5 round 1 and need the human's approval at P6. |
