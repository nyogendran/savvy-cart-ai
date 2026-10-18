# SC-027 — v2.4: recommendation-first hierarchy, mobile touch targets, Karuppan profile

**Status:** READY_FOR_APPROVAL (revision 4; revision 1 approved) · **Ticket:** SC-027 (spec) · build ticket SC-028

Builds on the approved SC-025 spec. Every SC-025 and SC-023 rule stays unless it is listed under **Supersedes**. Prototype deadline 18 Oct 2026.

**Origin:** a UX review by another development assistant on 18 Oct 2026, checked against `src/savvycart/static/app.css` and `src/savvycart/http.py` at `8c2a4d0`. The human chose the full set of suggestions. Presentation only: no engine, agent, guardrail, or fixture change.

## Problem

1. The Offer Reality Check colors the "The terms pay you" box green even when it pays LKR 0, which reads as a good outcome.
2. The Plan step opens with solver jargon ("chosen by an exact optimizer (OR-Tools CP-SAT, status OPTIMAL)") instead of what to do.
3. The Why step shows the raw agent tool calls as an open list under the answer, competing with the answer.
4. Pantry rows show the full purchase-history sentence on every row, so the list is long and hard to scan.
5. Touch targets are below about 44 px (buttons about 42 px, question chips about 32 px, checkboxes 18 px, step pills about 34 px).
6. Karuppan appears only in the tagline; the household story (budget, cards, usual store) is not visible while the shopper changes it.
7. The sample-data banner is one long paragraph on every step.

## Supersedes

| Earlier rule | v2.4 rule |
| --- | --- |
| The Plan lead names the optimizer and its solver status | The Plan step opens with a recommendation sentence built from the engine plan; the optimizer, solver status, and engine steps move into a collapsed "How this was calculated" block |
| The Why step lists agent tool calls under a visible "Agent tools called" heading | The tool list and the "did not change your inputs" note sit in a collapsed "How this was calculated" block; the answer, its source line, the engine figures, and any re-plan warning stay visible |
| Each pantry row shows the full reason sentence | Each pantry row shows item, status, quantity, and a short timing label; the full reason sentence is in an expandable block on the same row |
| The banner shows the whole sample-data statement | The banner shows "Sample data, not live; savings are simulated." and the whole statement (`V2_BANNER`, unchanged) in an expandable block |
| The truth box is always green | The truth box is amber when the terms pay LKR 0 |

## In scope

1. **Karuppan profile card** below the site header, inside the form, before the step list, on every step and on the Offer Reality Check page. It is not a `section.step`.
   - Text: "Karuppan's household · Colombo", "Fictional demo profile", and "LKR {budget} budget · {n} cards · Usually shops at {usual store}".
   - The figures come from the request's current state: `state["budget"]` (thousands separators), `len(state["banks"])` ("no cards", "1 card", "{n} cards"), and `STORE_NAMES[state["usual_store"]]`. Nothing else is shown about the household.
   - The illustration is an inline SVG (no external asset, no network fetch), `aria-hidden="true"`, drawn only with palette colors plus one skin tone. The text carries the meaning.
   - Pantry step: full card (avatar about 56 px, three lines). Other steps: compact card (avatar about 32 px, one line on desktop; it may wrap at 520 px and below).
   - The facts line uses its own class (`profile-facts`), not the Offer page's `.facts` grid.
2. **First screen.** The Pantry lead starts with "Check what you need for your next shop." and keeps the existing method sentence. The banner change above applies to every page.
3. **Recommendation first on Plan.** Directly under the Plan heading, `<p class="recommendation" id="plan-recommendation">`:
   - "Shop on {Weekday} {d Mon} at {Store A} and {Store B}." (one store: "at {Store A}"; three or more: "A, B and C").
   - Then, for each bill with a card: "Pay with {bank} {product} at {Store}." If that card's offer is not a published bank offer (`source` other than `published`, today the HNB offers), the sentence ends " (fictional demo offer)." because the banner that says so is collapsed. If no bill has a card: "No card offer applies to this basket."
   - If the plan has no stores, the line says only "No store can price this basket."
   - Every word comes from `plan["day"]` and `plan["stores"]` (store id, `card`, and the offer's `source`); no new figure. The metrics follow (plan total with extra-trip cost, savings), then the simulated-savings note, unchanged.
   - If `plan["solver_status"]` is not `OPTIMAL`, a visible `p.notice` right after the recommendation says "The optimizer stopped before proving this is the cheapest plan (status {status})."
   - The lead keeps "{n} stores (you allowed up to {m})" and the promotions-then-one-card sentence. "OR-Tools CP-SAT, status {status}", the engine steps, and the trip cost per extra store move into `<details class="how"><summary>How this was calculated</summary>`.
   - On the Why and Approve steps, when any bill's card offer is not published, a visible `p.notice` right after the engine recap says "{Bank} card offers in this plan are fictional demo offers, not published by the bank." (the recap text itself is unchanged).
   - The control-basket page (action `refused`) uses the same rendering, but its recommendation starts "Control basket, priced with every demo card, one store, and Keells as the usual store: " because that basket ignores the shopper's wallet and the profile card.
4. **Simpler pantry rows.** Row order: checkbox, name, status chip, quantity. Below: a short timing label ("Due today", "Due in {n} days", "Overdue by {n} days"; unchanged text for not-enough-history and "You added this item."). Stale rows ("Not bought for a while") use the same labels, so they read "Overdue by {n} days". The full `_reason_text` sentence sits in `<details class="reason"><summary>{short label}<span class="sr-only">: {item name}</span></summary>…</details>` when there is a longer explanation, so every toggle has a distinct accessible name. The details block comes after the quantity input in source order (one extra tab stop per row, after the quantity), spans the name and quantity columns, and uses a muted summary style. Quantity inputs are right-aligned with tabular figures (folded in from the uncommitted change, by the human's choice).
5. **Offer Reality Check.**
   - `<div class="truth zero">` when `check["paid_lkr"] == 0`, styled with the amber warn colors (`--warn`, `--warn-soft`). Non-zero payouts stay green.
   - Right after the result block, a primary "Go to my shopping plan" button (`action=plan`); "Go" rather than "Back" because the check can be opened from Wallet before any plan was shown. The page's bottom nav is unchanged: Back (wallet) and "Next: plan my shopping", which the frozen README judge path names.
   - The Plan step's offer callout is unchanged in wording and stays above the engine details.
6. **Readable AI answers (Why step).** Visible order: engine figures recap, the ask box with chips, "You asked", the source line, the answer (`<p id="explanation-text">`), and any re-plan warning (`p.notice`). Then `<details class="how"><summary>How this was calculated: {n} agent tool calls</summary>` ("1 agent tool call"; "no agent tool calls" when there are none) containing the "did not change your inputs" note and `<ul class="tools" id="agent-tools">` (markup unchanged). The count keeps the agent's work visible to a viewer who does not open the block; the demo script opens it once.
7. **Mobile.** In `app.css`:
   - `button`, `select`, `input[type="number"]`, `input[type="text"]`, `input[type="date"]`, `button.chip`, and `details summary` have `min-height: 44px`.
   - Checkboxes and radios are 22 px; `.check` rows, the step pills, and the link-style buttons inside completed step pills (`nav.steps li button.linklike`, which otherwise inherit `min-height: 0`) have `min-height: 44px`.
   - No sticky wizard nav. Revision 2 (18 Oct 2026, the pre-agreed fallback): a sticky nav was built and measured at 375 × 812 px; on the Plan step its three buttons wrap and the bar is 177 px tall, covering about 22% of the screen, so it was dropped and the 44 px targets stay.
   - Inline rows (date with Update, add-item, question with Ask) may wrap at 375 px as long as nothing overflows.
   - Bill tables and `table.lines` sit in a horizontally scrollable wrapper so the page itself never scrolls sideways at 375 px.

## Out of scope

- Any change to `optimizer.py`, `planner.py`, `explain.py`, `offercheck.py`, `pantry.py`, `agent.py`, `guardrails.py`, `gemini.py`, fixtures, or figures. The default demo plan stays LKR 4,609, saving LKR 1,331.
- A configurable or multi-household profile; editing the profile from the card.
- Dark mode, new fonts, or a palette change (the existing palette is kept; white on `#0B6E4F` is about 6.26:1).
- Live Gemini verification (D1 still applies after deploy).

## Acceptance criteria

1. Given the default guest flow, every step and the Offer Reality Check page show the profile card with "Fictional demo profile" and an `aria-hidden` inline SVG. Given budget 9000, two cards, and usual store Cargills, the card reads "LKR 9,000 budget · 2 cards · Usually shops at Cargills"; given one card, "1 card"; given none, "no cards". **Verified by** `python -m pytest tests/test_v24_page.py::test_profile_card_reflects_current_selections_on_every_step -q`.
2. Given any page, the banner shows "Sample data, not live; savings are simulated." outside a `<details>`, and the escaped `V2_BANNER` inside one. **Verified by** `python -m pytest tests/test_v24_page.py::test_sample_data_notice_stays_visible_with_details_expandable -q`.
3. Given the default plan, `#plan-recommendation` directly follows the Plan heading and comes before the first `.metric`, names the plan's weekday, date, and every store in `plan["stores"]`, and has a "Pay with {bank} {product} at {store}" sentence for each bill with a card. Given HNB as the only card, the sentence ends "(fictional demo offer)." and the Why and Approve steps show the fictional-offer notice right after the recap (absent for the default plan). Given the control basket, it starts with the control-basket prefix and says "No card offer applies to this basket." Given a plan with no stores, it says only "No store can price this basket." Given a FEASIBLE solver status, the not-proven notice follows it. "CP-SAT", "Engine steps:", and "per extra store" appear only inside `details.how`. **Verified by** `python -m pytest tests/test_v24_page.py::test_plan_leads_with_a_recommendation_built_from_the_engine_plan -q`.
4. Given the sample history, each due or soon pantry row shows a short timing label (the stale row reads "Overdue by 19 days") with its item name for screen readers, every toggle's accessible name is distinct, and its full "Bought on … days" sentence is inside a `details.reason` on that row. Given days left of -2, -1, 0, 1, and 2, the labels are "Overdue by 2 days", "Overdue by 1 day", "Due today", "Due in 1 day", and "Due in 2 days"; a not-enough-history row keeps its unchanged reason text. **Verified by** `python -m pytest tests/test_v24_page.py::test_pantry_rows_show_a_short_timing_label_and_expandable_history -q`.
5. Given the sample Seylan offer on the default basket (pays LKR 0), the truth box has class `zero`. Given terms that pay more than zero, it does not. The `.truth.zero` CSS uses `var(--warn-soft)` and `var(--warn)`. The page has exactly one primary "Go to my shopping plan" button with `value="plan"`, right after the result, keeps "Next: plan my shopping" in the bottom nav, and pressing it renders the Plan step. **Verified by** `python -m pytest tests/test_v24_page.py::test_zero_payout_is_amber_and_offer_check_returns_to_the_plan -q`.
6. Given a scripted agent answer with three tool calls, `#agent-tools` is inside `details.how`, its summary reads "How this was calculated: 3 agent tool calls", and `#explanation-text` is not inside it. Given a re-plan, the re-plan `p.notice` is outside `details.how`. Given no tool calls, the summary reads "How this was calculated: no agent tool calls". **Verified by** `python -m pytest tests/test_v24_page.py::test_agent_tool_calls_sit_behind_how_this_was_calculated -q`.
7. Given `app.css`, the last `min-height` set for the button, select, number, text, date, chip, `.check`, step-pill, step-pill button, and `details summary` selectors is `44px`; the only button rule below 44 px is `button.linklike`, used only in the step pills; checkboxes and radios are 22 px; `.scroll` has `overflow-x: auto` and wraps every bill table and `table.lines`. **Verified by** `python -m pytest tests/test_v24_page.py::test_touch_targets_are_at_least_44px -q`.
8. Given a 375 px wide viewport (browser device emulation) on Pantry, Plan, Why, and the Offer Reality Check, `document.documentElement.scrollWidth <= 375` and every visible button, select, number, text, and date input, summary, and step pill is at least 44 px tall (`getBoundingClientRect().height`). **Verified by** a `Runtime.evaluate` check on each page in the Cursor browser, recorded with screenshots in `.adlc/evidence/SC-028-p6/` for the P6 packet.
9. Every earlier test still passes and the default demo plan is unchanged (LKR 4,609, saving LKR 1,331). **Verified by** `python -m pytest -q`.
10. The README checker passes. **Verified by** `python scripts/check_judge_readme.py`.

## Approved assumptions

| Id | Assumption |
| --- | --- |
| F1 | "Colombo" and the household framing come from the product vision persona (`specs/001-product-vision/spec.md`); the card says "Fictional demo profile". |
| F2 | The profile card mirrors state; it adds no input and no hidden field. |
| F3 | The illustration is a simple inline SVG drawn in this change (round head and shoulders with a shopping bag, palette greens, one warm skin tone, no exaggerated features), not a generated or downloaded image. If the human rejects it at P6, it is replaced by a "K" monogram in the same circle. |
| F4 | Existing test anchors stay byte-identical: the full `V2_BANNER`, `<ul class="tools" id="agent-tools">`, `<p id="explanation-text">`, wallet and plan button labels, "(you allowed up to n)", and the "Bought on …" sentence text. Every earlier test file is a frozen rail for SC-028; new tests go only in `tests/test_v24_page.py`. |
| F5 | P5 uses the same sequential lenses as SC-026 plus a cross-model review by Gemini; no frozen rail is touched. |
| F6 | Cut-off 15:00 Colombo on 18 Oct 2026 for v2.4 acceptance, before SC-025's 17:00 cut-off; if v2.4 is not accepted by then, v2.3 (main) is deployed. |
| F7 | The profile card reflects the last submitted choices; it updates on the next page load, not live while typing, and has no client script. |
| F8 | Revisions 3 and 4 (18 Oct 2026) fold in the P5 round-1 and round-2 fixes listed above. The README still says the tool list and pantry reasons are visible; it is frozen for SC-028, so its wording is a follow-up. The banner's short sentence repeats as the first sentence of the expanded `V2_BANNER`, which stays byte-identical (F4). |
