# SC-014 — v2: wallet, pantry from purchase history, multi-store day plan, guided UX

> Status: **APPROVED** (17 Oct 2026, P1 Gate 1)
> Ticket: **SC-014**
> Builds on: `.adlc/specs/SC-001-product-vision.md` (APPROVED). Every SC-001 rule stays in force unless this spec names it under **Supersedes**.
> Deadline: prototype submission **18 Oct 2026**, Asia/Colombo, three-hour buffer (SC-001 A2).

## Problem

A Colombo household holds several credit cards and shops at more than one chain. Each chain runs its own item promotions, and each bank runs card offers tied to a store, a weekday, a category, a minimum bill, and a cap. The household cannot tell **when** a staple will run out, **which** store and card to use for **which** items, or how much a promotion really saves.

Evidence from one real shopper's 26 Keells e-bills (5 May – 17 Oct 2026): gross spend LKR 217,729; every promotion combined saved LKR 7,630 (about 3.5%). Promotions were item-level (Nexus Deals 20–30%, Nexus fresh 20%, Quick Sales), not bill-wide. On four days the shopper paid at more than one store.

## Persona

**Karuppan**, fictional name. Colombo. Shops Keells and Cargills often, Glomark rarely, SPAR sometimes. Wallet: **Commercial Bank credit**, **Nations Trust Bank credit**, **HNB credit** (issuer and product ids only; never a card number). His purchase history is the de-identified real e-bill history in `samples/purchase-history.json` plus fictional Cargills and Glomark bills labeled `source: fictional`.

## Solution

1. **Pantry.** From purchase history, the engine estimates when each regular item runs low and lists the items due within the planning window, with the dates that justify each one.
2. **Day plan.** For a chosen day, an exact optimizer assigns the due items across up to two stores, picks one wallet card per store bill, applies store promotions and card offers with their rules, and charges an editable cost per extra store visit.
3. **Savings.** The plan shows what the household saves against two baselines: everything at the usual store with no offer, and the best single-store plan. A day sweep shows the best day to shop before items run out.
4. **Gemini.** Gemini reads new receipts into history lines and, through the one ADK agent, explains the plan using only engine numbers.
5. **Guided UX.** A five-step guest flow: Pantry, Wallet, Plan, Why, Approve.

## Supersedes (SC-001 rules replaced by this spec)

| SC-001 rule | v2 rule |
| --- | --- |
| One card product per shopper | A wallet of card products; one card is chosen per store bill |
| One store per plan, no split plans | Up to two stores per day plan (`max_stores` 1 or 2) |
| Out of scope: learned forecasts, pantry models, stock-out dates | A **rule-based** cadence estimate (median gap between purchase dates) is in scope. No model is trained (SC-001 A9 holds) |
| `running_low` is a fixture flag | `running_low` is computed from history; the fixture flag is no longer read by the v2 flow |
| Three stores | Four stores: Keells, Cargills, SPAR, Glomark |
| Two offer rules, Keells only | Card offers for three banks across stores, plus store item promotions; all fictional demo shapes (SC-001 A8 holds) |

The v1 single-store optimizer, its fixtures, the v1 API endpoints, and their tests stay unchanged and green. v2 adds new modules beside them. The v1 guest page is **retired**: the v2 flow replaces it at `/`, and the v1 page tests (`tests/test_guest_page.py`, `tests/test_agent_page.py`) are retired with it. Their guarantees that still apply (no-model 503, number filter, injection isolation, failure logging) are re-asserted by v2 tests.

## In scope

1. **History file.** `scripts/build_history.py` reads e-bill PDFs from the git-ignored folder `samples/purchase-history/` and writes `samples/purchase-history.json`. Each bill keeps only: `date`, `chain`, `source` (`receipt` or `fictional`), lines (`raw`, `qty`, `unit_lkr`, `amount_lkr`), item promotions (`label`, `line`, `percent`, `amount_lkr`), `gross_lkr`, `net_lkr`. It drops names, email addresses, branch names and addresses, bill, cashier, loyalty and card numbers, and links. Unit and line amounts are integer LKR, rounded half up from the bill. The PDFs are never committed.
2. **Catalog v2.** `fixtures/v2/catalog.json` holds the shopper's regular items (about 15 SKUs drawn from the history), each with `category` (`staple`, `fresh`, or `household`) and a price at each of the four stores. Keells prices are the latest observed unit price in the history (`source: receipt`, `observed_on`). Prices at other stores are `source: fictional` and stay within ±10% of the observed Keells price, so Keells wins some plans and loses others. `fixtures/v2/history-map.json` maps receipt descriptions to SKU ids.
3. **Offers v2.** `fixtures/v2/offers.json` holds card offers (`bank`, `product`, `store_id`, `days`, `rate_bps`, `min_bill_lkr`, `cap_lkr`, `include_categories`, `exclude_categories`, `valid_to`, `stackable: false`) and store promotions (`store_id`, `sku_id` or `category`, `rate_bps`, `days`, `valid_to`). Every row is a labeled demo shape.
4. **Pantry engine** (`src/savvycart/pantry.py`). For each SKU with purchases on at least two distinct dates: `cadence_days` = median gap in days; `usual_qty` = median quantity per purchase; `next_due` = last purchase date + `cadence_days`; `days_left` = `next_due` − today. Status `due` when `days_left` ≤ 3 **and** the SKU has at least three purchase dates; `soon` when `days_left` ≤ 7 (or when a two-date SKU would otherwise be `due`); else `ok`. SKUs bought once are `unknown` and never pre-checked. Each item carries a reason string built only from these numbers and dates.
5. **Day planner** (`src/savvycart/planner.py`, Google OR-Tools CP-SAT). Inputs: confirmed lines, day, wallet, `max_stores`, `trip_cost_lkr` (default 250, editable, labeled an assumption), usual store. Rules:
   - A store promotion lowers that line's price at that store first. Promotions do not stack with each other.
   - A card offer applies to one store bill when its bank is in the wallet, its store and day match, and it has not expired. Eligible subtotal is the sum of promoted line prices whose category is included and not excluded.
   - Card discount = min(⌊eligible × rate_bps / 10000⌋, cap) when eligible ≥ minimum, else 0. At most one card offer per store bill.
   - Every line goes to exactly one store that prices it. A line with no price anywhere is `unpriced` and the plan is `incomplete`.
   - Objective: minimize promoted shelf total − card discounts + `trip_cost_lkr` × (stores used − 1).
   - Equal-cost plans break ties deterministically: fewer stores, then the usual store, then store id. CP-SAT runs with one worker and a fixed seed, so identical inputs return identical plans.
   - Output: per store, the lines, the chosen card, promotion savings, card discount, bill total; plan totals; both baselines; the saving against each; solver status `OPTIMAL`.
6. **Day sweep.** The planner runs for each of the next seven days and reports the cheapest day on or before the earliest `next_due` among the confirmed lines.
7. **Agent.** The one ADK agent gains `get_pantry` and `plan_day` tools and **may re-plan**, for example to compare another day or a smaller wallet. **Explain this plan** sends the confirmed inputs and the engine's plan. The Why step lists every tool the agent called with its arguments, says plainly when the agent re-planned with different inputs, and filters the agent's text against the numbers in the engine plan plus every tool result from that agent run (the SC-006/SC-011 filter, widened to tool outputs). Any number from no engine output is dropped.
8. **Guided UX.** Server-rendered HTML with one CSS file and no frontend framework or login. Steps: **Pantry** (due and soon items, reasons, checkboxes), **Wallet** (cards as issuer and product), **Plan** (store cards with items, card, savings bar, both baselines, day sweep), **Why** (agent explanation, tools called), **Approve** (MOCK, `No order is sent.`). Mobile-first layout with a viewport meta tag, labeled form controls, visible focus, one `h1`, a `main` landmark, and text that never relies on color alone. The sample-data banner stays on every step. **Use sample receipt** and **Extract this image** stay available to add a receipt to history.

## Out of scope

Live prices or offers. Scraping. Card numbers. Real orders or payments. Login. A trained model of any kind. More than two stores in one day plan. Delivery and online channels. Loyalty points in rupees. Sinhala or Tamil UI.

## Acceptance criteria

1. Given the committed history, the history file contains no email address, card or loyalty number, branch address, or shopper name, and every amount is an integer. **Verified by** `python -m pytest tests/test_history.py::test_history_is_deidentified -q`.
2. Given the committed history and today 18 Oct 2026, a SKU bought on dates with a known median gap gets that `cadence_days`, the matching `next_due`, and status `due`, `soon`, or `ok` by the thresholds; a SKU with only two purchase dates is never `due`; a SKU bought once is `unknown`. **Verified by** `python -m pytest tests/test_pantry.py::test_cadence_and_status_follow_history -q`.
3. Given a basket where a second store's card offer saves more than `trip_cost_lkr`, the planner returns a two-store plan that is cheaper than the best single-store plan, with solver status `OPTIMAL`. **Verified by** `python -m pytest tests/test_planner.py::test_split_beats_single_store_when_offer_pays -q`.
4. Given the same basket with `trip_cost_lkr` larger than that saving, the planner returns a single-store plan. **Verified by** `python -m pytest tests/test_planner.py::test_trip_cost_prevents_tiny_splits -q`.
5. Given a wallet without the bank of an offer, that offer never applies; given two eligible cards at one store, only one card offer applies to that bill. **Verified by** `python -m pytest tests/test_planner.py::test_wallet_gates_offers_and_one_card_per_bill -q`.
6. Given a store bill under an offer's minimum, the card discount is 0; above the minimum it is capped at `cap_lkr`; after `valid_to` it is 0. **Verified by** `python -m pytest tests/test_planner.py::test_minimum_cap_and_expiry_hold_per_bill -q`.
7. Given a store promotion and a card offer on the same line, the promotion lowers the line price first and the card offer is computed on the promoted price. **Verified by** `python -m pytest tests/test_planner.py::test_promotion_applies_before_card_offer -q`.
8. Given the planner output, the total saving against the usual-store baseline equals the baseline total minus the plan total. **Verified by** `python -m pytest tests/test_planner.py::test_savings_equal_baseline_minus_plan -q`.
9. Given the sample history, the day sweep reports a cheapest day on or before the earliest `next_due`. **Verified by** `python -m pytest tests/test_planner.py::test_day_sweep_stays_before_run_out -q`.
10. Given `GET /` on the v2 flow, the page has a viewport meta tag, one `h1`, a `main` landmark, a label for every input and select, the sample-data banner, and the step names Pantry, Wallet, Plan, Why, Approve. **Verified by** `python -m pytest tests/test_v2_page.py::test_guided_flow_is_accessible -q`.
11. Given the sample path on the v2 flow with a fake model, the Plan step shows each store bill with its chosen card and the saving against both baselines, and the Why step lists the agent tools called. **Verified by** `python -m pytest tests/test_v2_page.py::test_plan_step_shows_store_bills_and_savings -q`.
12. Every remaining test passes, with only the two retired v1 page test files removed. **Verified by** `python -m pytest -q`.
13. Given two identical planner calls, the plans are identical; given equal-cost options, the plan with fewer stores, then the usual store, wins. **Verified by** `python -m pytest tests/test_planner.py::test_plans_are_deterministic_with_tie_breaks -q`.
14. Given an agent run that re-plans with a different day, the Why step names the re-plan and its arguments, and every number in the shown text appears in the engine plan or in a tool result from that run. **Verified by** `python -m pytest tests/test_v2_page.py::test_agent_replan_is_disclosed_and_numbers_are_grounded -q`.
15. Given the history builder, every committed bill's line amounts sum to its gross total within LKR 1 per line of rounding. **Verified by** `python -m pytest tests/test_history.py::test_bill_lines_sum_to_gross -q`.

## Approved assumptions

| Id | Assumption |
| --- | --- |
| B1 | The real e-bills belong to the human, who approved their de-identified use. The PDFs stay git-ignored. |
| B2 | Cargills, SPAR, and Glomark prices and all card offers are fictional demo shapes, labeled in data and UI. |
| B3 | Default `trip_cost_lkr` 250 is an assumption the shopper edits; it is shown with the plan. |
| B4 | Cadence is a median of gaps, not a forecast model. Fewer than two purchase dates means `unknown`. |
| B5 | Planning window is seven days from the chosen day. `due` ≤ 3 days, `soon` ≤ 7 days. |
| B6 | `max_stores` is 1 or 2 for this prototype. |
| B7 | OR-Tools CP-SAT is the solver; it is open source from Google and runs inside the Cloud Run container. |
| B8 | v1 endpoints and their tests remain; the v1 guest page and its two page test files are retired. |
| B9 | No v1 fallback deploy: the human chose to submit v2 only, accepting the time risk. |
| B10 | Fictional prices at other stores stay within ±10% of the observed Keells price. |
| B11 | An item needs three purchase dates before it can be `due`. |
| B12 | The agent may re-plan; re-plans are disclosed with their arguments, never silent. |

## Mitigations required by the criteria

| Failure | Where it is handled |
| --- | --- |
| Personal data from real e-bills reaches git | AC 1 and assumption B1 |
| "Runs out" claim with no basis | AC 2 (dates and median shown) |
| Split basket that saves less than the extra trip | AC 4 |
| Offer from a card the shopper does not hold, or two cards on one bill | AC 5 |
| Minimum, cap, or end date ignored per store bill | AC 6 |
| Promotion and card offer stacked in the wrong order | AC 7 |
| Savings figure that does not add up | AC 8 |
| Best day falls after items run out | AC 9 |
| UI unusable on a phone or with a keyboard | AC 10 |
| Plan on screen disagrees with engine output | AC 11 |
| v2 breaks v1 guarantees | AC 12 |
| Video and live app show different plans | AC 13 |
| Agent explains a plan that is not on screen | AC 14 |
| History parser corrupts amounts or dates | AC 15 |
