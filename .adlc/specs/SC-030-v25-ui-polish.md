# SC-030 — v2.5: UI polish (pantry spacing, quantity steps, bill tables, demo wording)

**Status:** READY_FOR_APPROVAL (revision 4; revision 3 approved) · **Ticket:** SC-030 (spec) · build ticket SC-031 · absorbs SC-029 (README wording)

Builds on the approved SC-027 spec (revision 7). Every SC-027, SC-025, and SC-023 rule stays unless it is listed under **Supersedes**. Prototype deadline 18 Oct 2026.

**Origin:** the human's review of v2.4 on 18 Oct 2026 (screenshots of the pantry rows, the add-item row, and the bill tables), with all five observations chosen for v2.5, polish before deploy.

## Problem

1. Each pantry row has a large gap between the item name and its timing label, because SC-027 gave every `details summary` a 44 px minimum height plus 10 px padding.
2. The "Add an item" quantity shows its number left-aligned and wider than the row quantities, so it does not line up with the quantity column above.
3. Items sold by weight take any amount (`step="any"`, minimum 0.001), and history medians such as 1.034 kg are suggested; people buy loose produce in half kilos.
4. Bill tables repeat "LKR" in every Shelf and Promotion cell, show no unit price, and repeat "(receipt price)" or "(fictional price)" on every row.
5. Demo wording is scattered: the date control reads "Pretend today is (demo control; the history ends 17 Oct 2026)", and the README still describes v2.3 visibility (SC-029).

## Supersedes

| Earlier rule | v2.5 rule |
| --- | --- |
| SC-027: every `details summary` has `min-height: 44px` | Pantry-row summaries (`.item details.reason summary`) have `min-height: 28px` and no vertical padding (above the WCAG 2.2 target-size minimum of 24 px); every other summary keeps 44 px |
| SC-025 / E5: items sold by weight keep 3 decimals; inputs accept any amount | Items sold by weight snap to 0.5 kg: the suggestion is the history median rounded to the nearest 0.5 kg (at least 0.5), inputs use `min="0.5" step="0.5"`, and a typed amount is rounded to the nearest 0.5 kg (half up, at least 0.5). Items sold as units stay whole numbers |
| The default demo plan is LKR 4,609, saving LKR 1,331 | The default demo plan is LKR 4,604, saving LKR 1,328 (only Banana ambul changes, 1.034 kg to 1 kg); the engine is unchanged |
| Bill rows show "LKR" in Shelf and Promotion and a price source per row | Bill tables show amounts in LKR column headers, plain whole-rupee numbers in rows, a Unit price column, and one price-source line per bill |
| The date control label "Pretend today is (demo control; the history ends 17 Oct 2026)" | The label is "Planning date (17 to 31 Oct 2026)"; why the range exists moves into the banner's "What is real in this demo?" block |
| `tests/test_v21_page.py` asserts the old date label and the added papaya's `min="0.001" ... step="any"`; `tests/test_v22_page.py` asserts `step="any"` for carrot and "saving 1331 LKR" | Those four assertions change to the v2.5 rules above; every other assertion in those files is unchanged |
| Revision 2 (human-approved on 18 Oct 2026): frozen tests that assert figures computed on the default basket | Re-baselined numbers only, no logic change: `tests/test_guardrails.py` (the live default total and saving 4,609 / 1,331 become 4,604 / 1,328 in the scripted agent answer and its expected text), `tests/test_v22_page.py` (sample offer headline LKR 594 becomes 593 and the shortfall LKR 2,468 becomes 2,475; pasted offer "not LKR 594" becomes 593 and "not LKR 1,188" becomes 1,186), and `tests/test_v2_page.py` (the scripted re-plan's Banana ambul quantity 1.034 becomes 1, to match the shopper's basket) |
| Revision 3 (human-approved on 18 Oct 2026): SC-019/SC-023 disclose every agent `plan_day` call with different inputs as "The agent re-planned with different inputs", even when the call was refused or failed; `tests/test_v2_page.py::test_malformed_agent_tool_calls_do_not_break_the_page` asserts that wording; `tests/test_v22_page.py` line 149 checks "You save 4609" | A refused or failed `plan_day` call (its response has `error`) is disclosed as "The agent tried to re-plan with different inputs ({differences}); the call was refused, so nothing was re-planned.", visible outside `details.how`; successful re-plans keep the existing notice. The malformed-call assertion changes to the new wording and gains one added line asserting the refused wording and the absence of the old one, and line 149 checks "You save 4604". Calls are compared by their normalised request (cards sorted, lines sorted with normalised quantities, a missing argument meaning the shopper's): a refused request that a completed call repeats (a failed call retried successfully) is not shown; refused requests are shown one sentence per distinct difference text, however often the agent retried; completed re-plans are each disclosed as before; the cards in a difference are listed sorted; plan_day calls are paired only with plan_day responses |

## In scope

1. **Pantry spacing.** `.item details.reason summary { min-height: 28px; padding: 0; }`; the summary sits directly under the item name (no extra row gap). Other summaries are unchanged.
2. **Add-item row.** `#add_qty` is right-aligned with tabular figures and the same width as row quantity inputs (5em); it uses `min="0.5" step="0.5"`. The Add button stays at the end of the row. The note under it adds "Packs are whole numbers, so a half pack is rounded up; loose produce is in half kilos."
3. **Quantity steps.** In `_pantry_view` (`src/savvycart/http.py`), items with `divisible` true get `max(0.5, round_half_up(qty / 0.5) * 0.5)` for both the suggestion and a typed amount; whole-unit items are unchanged. Row inputs for weighed items render `min="0.5" step="0.5"`, and the value always satisfies that step. `pantry.py` and the engine are not changed.
4. **Bill tables** (`_render_bill`):
   - Columns: Item, Qty, Unit price (LKR), Shelf (LKR), Promotion (LKR). Qty shows "{n} kg" for weighed items and "{n}" otherwise. Unit price is the catalog price for that store (per kg or per unit). Row amounts are whole rupees with thousands separators and no "LKR"; a row with no promotion shows "-".
   - The footer keeps "Card discount LKR {n}" and "Bill total LKR {n}".
   - One `p.source` line per bill: "Prices from Keells receipts." when every line's `price_source` is `receipt`, "Fictional demo prices." when every line is `fictional`, otherwise "Prices from receipts except those marked * (fictional)." with a `*` after each fictional row's name.
   - "(fictional demo offer)" qualifiers, the "Offer: fictional demo shape." line, and published-offer terms are unchanged.
   - No ".00" decimals anywhere: the engine computes whole rupees.
   - Numeric headers may wrap; tables have `table-layout: fixed`, a 36% item column, and `min-width: 600px` so no header or cell overflows its column (tables scroll inside the card on narrow screens).
   - Bills render one per row at full width (the bills container is no longer `grid two`), because five columns are cramped in a half-width card.
5. **Demo wording.**
   - Date label: "Planning date (17 to 31 Oct 2026)". The select and its Update button are unchanged.
   - The banner's `details` block keeps `V2_BANNER` byte-identical and adds a second paragraph: "The planning date runs from 17 to 31 Oct 2026 because the sample purchase history ends on 17 Oct 2026."
   - Wording audit: the remaining mentions stay because each sits next to a figure that would otherwise read as fact or names a sample action: the simulated-savings note on Plan, "Fictional demo profile", "(fictional demo offer)", "Offer: fictional demo shape.", the HNB notice on Why and Approve, the offer page's promotions note, and the "Use sample receipt" / "Use the sample offer" buttons.
6. **README (absorbs SC-029).** The judge path tells the judge to open a pantry row's timing label for the purchase-history reason and "How this was calculated" for the agent's tool calls; it mentions the profile card and the Plan recommendation; and it states the new default figures (LKR 4,604, saving LKR 1,328; best single store beaten by LKR 63; sample offer headline LKR 593, LKR 2,475 short).

## Out of scope

- `pantry.py`, `planner.py`, `optimizer.py`, `offercheck.py`, `agent.py`, `guardrails.py`, `gemini.py`, fixtures. The agent's `get_pantry` tool still reports history medians to 3 decimals; the page's confirmed basket (0.5 kg steps) is what the agent is told to price.
- The review reports under `docs/report/`, which are dated records and keep the figures they reviewed.
- Decimal currency formatting.

## Acceptance criteria

1. Given the default pantry, every `.item details.reason summary` has a computed height of at least 24 px and at most 30 px, and the gap between the bottom of the item name label and the top of its summary is at most 8 px; every other visible summary is still at least 44 px. **Verified by** `python -m pytest tests/test_v25_page.py::test_pantry_summary_sits_under_the_item_name -q` (CSS rules) and a `Runtime.evaluate` measurement at 1280 px and 375 px recorded in `.adlc/evidence/SC-031-p6/`.
2. Given the default pantry, `#add_qty` is `type="number"` with `min="0.5" step="0.5"`, and the CSS gives it `text-align: right` and `width: 5em`. **Verified by** `python -m pytest tests/test_v25_page.py::test_add_item_quantity_matches_the_row_quantities -q`.
3. Given the default pantry, every weighed item's input has `min="0.5" step="0.5"` and a value that is a multiple of 0.5 (Banana ambul is 1); given typed amounts 0.2, 0.74, 0.75, and 1.26 kg for carrot, the Plan uses 0.5, 0.5, 1, and 1.5 kg; packs stay whole. **Verified by** `python -m pytest tests/test_v25_page.py::test_weighed_items_snap_to_half_kilos -q`.
4. Given the default flow, the Plan total is LKR 4,604 and the saving against Keells is LKR 1,328, and both appear on the Plan and Why steps. **Verified by** `python -m pytest tests/test_v25_page.py::test_default_plan_figures_after_half_kilo_steps -q`.
5. Given the default plan, each bill table's header cells are "Item", "Qty", "Unit price (LKR)", "Shelf (LKR)", "Promotion (LKR)"; no body cell contains "LKR"; each weighed row's Qty ends in " kg"; each Unit price equals the catalog price for that store; the footer has "Card discount" and "Bill total" with "LKR"; the Keells bill has exactly one "Prices from Keells receipts." line and the Cargills bill exactly one "Fictional demo prices." line; no row contains "(receipt price)" or "(fictional price)"; the bills container is not `grid two`; a bill mixing sources marks fictional rows with "*" and shows the mixed legend. **Verified by** `python -m pytest tests/test_v25_page.py::test_bill_tables_show_unit_prices_and_one_price_source_line -q`.
6. Given any page, the date control is labelled "Planning date (17 to 31 Oct 2026)", the words "Pretend" and "demo control" do not appear, and the banner `details` contains the escaped `V2_BANNER` plus the planning-date paragraph. **Verified by** `python -m pytest tests/test_v25_page.py::test_demo_wording_is_consolidated -q`.
7. Given README.md, the judge path names "How this was calculated", the pantry timing label, the profile card, the Plan recommendation, and LKR 4,604 / 1,328, and no longer states LKR 4,609. **Verified by** `python -m pytest tests/test_v25_page.py::test_readme_describes_v25 -q` and `python scripts/check_judge_readme.py`.
8. Given a 375 px viewport on Pantry, Plan, Why, and the Offer Reality Check, `document.documentElement.scrollWidth <= 375` and every visible control other than pantry-row summaries is at least 44 px tall. **Verified by** a `Runtime.evaluate` check in the Cursor browser recorded in `.adlc/evidence/SC-031-p6/`.
9. Every test passes, with only the superseded assertions (the four above plus the revision-2 re-baselines) changed in earlier test files. **Verified by** `python -m pytest -q` and `git diff ec794e4 -- tests/test_v2_page.py tests/test_v21_page.py tests/test_v22_page.py tests/test_guardrails.py` showing only those assertions (14 changed lines and 1 added assertion line).

## Approved assumptions

| Id | Assumption |
| --- | --- |
| G1 | Half-kilo steps match how loose produce is sold; the 0.5 kg minimum applies to every weighed item, including receipt-added amounts (the receipt note keeps the receipt quantity). |
| G7 | No deck or video-script files outside the repo state the old figures yet. |
| G9 | Every agent `plan_day` call has a recorded response (the real ADK loop records one, including guardrail refusals); a call with no recorded response, which only scripted test runners produce, is treated as a completed re-plan. |
| G8 | Browsers block submitting an off-step weight (for example 0.74 kg) with a native validation message; server-side snapping covers non-browser clients and the agent. Accepted. |
| G2 | 28 px pantry-row summaries meet WCAG 2.2 target size (24 px minimum); the main controls keep 44 px. |
| G3 | Unit price comes from the catalog (`prices[store].amount_lkr`), which is what the engine multiplies by quantity. |
| G4 | Whole rupees, no decimals, because the engine computes and rounds in whole rupees. |
| G5 | P5 uses fresh-context reviewers plus a cross-model Gemini review, as in SC-028. |
| G6 | Polish before deploy (the human's choice); SC-025's 17:00 Colombo deploy cut-off still applies, so if v2.5 is not accepted by 16:00 Colombo, v2.4 (main at the SC-028 commits) is deployed. |
