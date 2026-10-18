# SC-023 — v2.2: Offer Reality Check, Gemini-necessary receipts, ask the agent, number-role guard

Builds on the approved SC-019 spec. Every SC-019 rule stays unless it is listed under **Supersedes**. Prototype deadline 18 Oct 2026.

**Origin:** the human asked for this work on 18 Oct 2026. P1 approval is the human's recorded spec-approval gate; P6 behavioral acceptance stays with the human.

## Problem

Shoppers receive bank offers as SMS or web headlines ("10% off on Total Bill every Saturday") whose terms exclude staples, require a minimum, cap the discount, and forbid combining with store offers. Offer Reality Check makes that gap visible on the household's own basket: Gemini reads the terms into a fixed schema, the shopper confirms them, and deterministic code shows what the headline promises against what the terms actually pay.

## Supersedes

| SC-019 rule | v2.2 rule |
| --- | --- |
| Uploaded receipt lines count only when their text matches a known Keells description | A line also counts when Gemini matched it to a v2 catalog item with confidence of at least 0.6 |
| Receipt quantities are whole units | v2 uploads keep fractional quantities (3 decimals) |
| The Why step asks one fixed question | The shopper may type a question of up to 300 characters; the fixed question is the default |
| Card offers count every eligible line at its promoted price | A card offer may also exclude listed items, limit units per item, measure its minimum on the whole bill, and refuse lines that carry a store promotion. Existing offers keep their current behavior. |

## In scope

1. **Offer Reality Check** (Wallet step, "Check a card offer"). The shopper pastes an offer's text or uploads a screenshot. Gemini reads it into a fixed JSON schema (bank, store, days, percent, minimum and what it applies to, cap, excluded items quoted as printed, units per item, whether it combines with store offers, channel, end date). Code validates every field, maps excluded items to catalog items by name, and shows the rule as an editable form the shopper confirms. **Use the sample offer** loads the Seylan Bank Keells Saturday terms captured from seylan.lk on 17 Oct 2026 (strategy report) with a checked-in extraction, so the path works without a model.
2. The engine then prices the shopper's basket at that store on the offer's next valid day and shows, line by line: what the headline suggests (percent × basket shelf total), what the terms pay (excluded items, promoted items that cannot combine, unit limits, minimum, cap), and the engine's best plan if the shopper held that card, against their current plan.
3. **Receipts need Gemini.** The v2 upload prompt lists the v2 catalog; Gemini's catalog match is used when the text match fails; fractional quantities survive.
4. **Ask the agent.** A question box on the Why step. Off-topic questions are declined by instruction; every number still passes the grounding filter.
5. **Number-role guard.** A sentence that states the plan total as a saving, or the saving as the total, is dropped.
6. **Agent sees the session's receipts.** `get_pantry` includes purchases added from receipts in this session.
7. Receipt extraction no longer blocks the event loop.

## Out of scope

- Storing offers or receipts (no database); live bank pages fetched by the app; real card eligibility checks.

## Acceptance criteria

1. Given the sample Seylan offer and a basket containing milk powder and red dhal, the reality check lists both as excluded, applies 10% only to eligible lines, and pays LKR 0 when the bill is under LKR 8,000. **Verified by** `python -m pytest tests/test_offer_check.py -q`.
2. Given an eligible basket over the minimum, the paid discount equals min(10% of eligible lines, LKR 1,000), and the planner, given the same rule, gives the same discount at that store. **Verified by** `python -m pytest tests/test_offer_check.py -q`.
3. Given model output with out-of-range or invented fields, validation clamps or rejects them and never invents a cap or minimum. **Verified by** `python -m pytest tests/test_offer_check.py -q`.
4. Given a fake model, the Wallet step's pasted-offer path renders the confirm form and the result; without a model it says reading is unavailable and the sample still works. **Verified by** `python -m pytest tests/test_v22_page.py -q`.
5. Given a receipt line whose text matches nothing but whose Gemini catalog match has confidence ≥ 0.6, it is added with its fractional quantity. **Verified by** `python -m pytest tests/test_v22_page.py -q`.
6. Given an agent answer that swaps the total and the saving, the swapped sentence is dropped. **Verified by** `python -m pytest tests/test_v22_page.py -q`.
7. Every earlier test still passes. **Verified by** `python -m pytest -q`.

## Approved assumptions

| Id | Assumption |
| --- | --- |
| D1 | If live Gemini offer reading fails after deploy, the demo uses the sample offer and says so; the schema is not patched on deadline day. |
| D2 | Exclusions are matched to catalog items by name; the shopper confirms or corrects them before the check counts. |
| D3 | The free-text question box stays on the public URL; every number passes the grounding filter and the swapped-role guard; the 20-a-minute explanation limit applies. |
| D4 | The default demo numbers stay as in v2.1 (LKR 4,609, saving LKR 1,331); existing offers price exactly as before. |
| D5 | P5 uses a signed cross-model review by Gemini, because the change touches files frozen by SC-012. |
| D6 | Cut-off 17:00 Colombo on 18 Oct 2026; if v2.2 is not accepted by then, v2.1 (main) is deployed. |
| D7 | The Seylan sample terms were captured from seylan.lk on 17 Oct 2026 (strategy report); Savvy Cart is not affiliated with Seylan Bank. |
