# SC-019 — v2.1: real wizard, bounded planning date, add items, receipt upload, offer suggestions, multi-buy promotions, real bank offers, up to four stores, mock partner endpoints, mock delivery quote

Builds on the approved SC-014 spec. Every SC-014 rule stays unless it is listed under **Supersedes**. Prototype deadline 18 Oct 2026.

## Problem

The human tried the v2 flow and found ten gaps:

1. The planning date accepts any date, the page does not refresh when it changes, and a past date still counts purchases made after it (verified: `pantry.py` never skips bills dated after `today`).
2. The native date picker flashes a black window before it opens and cannot be styled.
3. The shopper cannot add an item to the basket.
4. **Use sample receipt** and **Extract this image** work, but the shopper cannot upload their own receipt, and the page does not say what was added.
5. All five steps pile up on one page; it is not a wizard.
6. When a card offer misses its minimum, the page states the gap but gives no help.
7. Store promotions are only a percent off; a fixed price with a quantity limit (for example LKR 500 instead of LKR 580, at most 3) is not supported.
8. Every card offer is fictional, although the human supplied the published supermarket offers of two banks.
9. A day plan is limited to two stores.
10. There is no delivery step.

## Supersedes (SC-014 rules replaced by this spec)

| SC-014 rule | v2.1 rule |
| --- | --- |
| B2: all card offers are fictional demo shapes | Nations Trust Bank and Commercial Bank in-store supermarket offers are transcribed from the banks' public listing pages captured on 18 Oct 2026, each with `source_url` and `captured_on`. HNB offers stay fictional and labeled. |
| B6: `max_stores` is 1 or 2 | `max_stores` is 1, 2, 3, or 4 |
| In scope 8: the five steps render on one page | One step at a time with Back and Next; state carried in the form |
| Planning date: any ISO date the form sends | A labeled demo control limited to 17 Oct 2026 to 31 Oct 2026 |
| SC-001: the page never suggests items to reach a minimum | The page may suggest items, only from the shopper's own pantry items due within 14 days and not already in the basket, never adds them itself, and shows the engine's net effect |
| Store promotions are a percent off a SKU or category | Also a fixed unit price for up to `max_qty` units of one SKU |

## In scope

1. **Pantry cut-off.** `pantry(bills, ..., today)` ignores every bill dated after `today`.
2. **Planning date control.** A `select` labeled "Pretend today is (demo control)" lists every date from 2026-10-17 to 2026-10-31; any other value falls back to the default 2026-10-22. Changing it reloads the Pantry step (a small inline script submits the form; the **Update** button does the same without JavaScript).
3. **Wizard.** Each response renders exactly one step section (Pantry, Wallet, Plan, Why, or Approve), a step indicator with the current step marked `aria-current="step"`, and Back / Next buttons. Earlier choices travel in hidden fields so Back keeps them. The banner, one `h1`, `main`, labels, and visible focus stay on every step.
4. **Add an item.** On the Pantry step a `select` of every catalog item not already listed as due or soon, with a quantity and an **Add** button, adds that item to the basket. Items outside the catalog cannot be added (no price).
5. **Receipt.** The Pantry step offers **Upload a receipt photo** (file input, JPEG or PNG, the existing `/v1/receipts` size limit) and **Use sample receipt**. Upload forwards the bytes to `/v1/receipts`; the image is never written to disk, storage, or logs. After either, the page lists the lines it added and the lines it left out. Without a model, upload says the live extract is unavailable and adds nothing. **Extract this image** is removed.
6. **Offer-minimum suggestions.** For each card offer that applied to a bill's store and day but paid 0 because of its minimum, the Plan step may show one suggestion: the cheapest set of at most three pantry items that are not in the basket, are eligible for that offer, and fall due within 14 days of the planning date, such that adding them reaches the minimum. The suggestion shows the items, their cost at that store, and the engine's re-planned total with them, and states plainly "Only if you need these soon. Savvy Cart does not add them." It is shown only when the engine's re-planned total is lower than the current total plus the items' shelf cost.
7. **Fixed-price promotions.** A store promotion may be `{"type": "fixed_price", "store_id", "sku_id", "price_lkr", "max_qty", "days", "valid_to"}`: up to `max_qty` units cost `price_lkr` each, the rest cost shelf price. Percent and fixed-price promotions do not stack; each line takes the one that saves more. Card offers are computed on the promoted line price. At least two fixed-price demo promotions exist, one of them UHT milk 1 L at Cargills, LKR 500 for up to 3 (the human's example).
8. **Real bank offers.** `fixtures/v2/offers.json` replaces the fictional NTB and Commercial Bank card offers with these published in-store supermarket offers (captured 18 Oct 2026): NTB Mastercard credit 25% at Keells every Sunday till 31 Oct 2026; NTB Mastercard credit 25% at Cargills Food City every Wednesday till 31 Oct 2026; Commercial Bank credit up to 25% at Keells every Saturday till 31 Oct 2026; Commercial Bank credit up to 25% at Cargills Food City every Friday till 30 Oct 2026; Commercial Bank credit and debit up to 30% on fresh items at Glomark every Wednesday till 28 Oct 2026; Commercial Bank credit up to 20% on fresh items at SPAR every Tuesday till 27 Oct 2026. Each has `source_url`, `captured_on`, and the `headline` text. Minimum bill, cap, and category limits are not published on the listing pages, so each carries `terms_source: "assumption"` and the page says "Minimum and cap are assumptions; check the bank's terms." Online-only offers and premium-card offers are left out. HNB offers stay fictional with `source: "fictional"`.
9. **Up to four stores.** The planner accepts `max_stores` 1 to 4; the Wallet step offers 1 to 4; the trip cost applies to each store after the first.
10. **Mock partner endpoints.** `GET /mock/stores` lists the four stores; `GET /mock/stores/{store_id}/catalog` returns that store's prices and promotions; `GET /mock/banks` and `GET /mock/banks/{bank_id}/offers` return card offers. Every response carries `"mock": true` and the data label, and is built from the same fixtures the engine reads (one source of truth). Unknown ids return 404.
11. **Mock delivery quote.** The Approve step offers "Pickup" or "Delivery (MOCK)". Delivery shows an assumed fee per store bill (default LKR 350, editable, labeled an assumption) and the sentence "No booking is made. Savvy Cart is not integrated with Uber, PickMe, or any store." The MOCK preview and `No order is sent.` stay.

## Out of scope

- Live scraping of store or bank websites, and any live price or stock.
- Separately deployed partner services, real store, bank, Uber, or PickMe integrations, real orders, payments, or bookings.
- HNB real offers (the listing page returned no content), online-only and premium-card offers.
- Items outside the catalog.

## Acceptance criteria

1. Given a bill dated after the planning date, the pantry ignores it. **Verified by** `python -m pytest tests/test_pantry_cutoff.py::test_bills_after_planning_date_are_ignored -q`.
2. Given the Pantry step, the planning date is a labeled `select` of 2026-10-17 to 2026-10-31, and a value outside that range falls back to 2026-10-22. **Verified by** `python -m pytest tests/test_v21_page.py::test_planning_date_is_a_bounded_demo_control -q`.
3. Given any action, the response contains exactly one step section, a step indicator with `aria-current="step"`, and Back on every step after Pantry; going Back keeps earlier choices. **Verified by** `python -m pytest tests/test_v21_page.py::test_wizard_shows_one_step_at_a_time -q`.
4. Given a catalog item that is not due, adding it puts it in the plan's bills; an id outside the catalog is ignored. **Verified by** `python -m pytest tests/test_v21_page.py::test_shopper_can_add_a_catalog_item -q`.
5. Given an uploaded photo and a fake model, the extracted lines are added and listed; without a model nothing is added and the page says so; the image is not stored. **Verified by** `python -m pytest tests/test_v21_page.py::test_uploaded_receipt_adds_listed_lines -q`.
6. Given a bill under an offer minimum, any suggestion lists only pantry items not in the basket that are due within 14 days and eligible for that offer, is never added to the basket by the page, and shows the engine's re-planned total. **Verified by** `python -m pytest tests/test_v21_page.py::test_offer_minimum_suggestions_use_only_items_due_soon -q`.
7. Given 4 units of UHT milk at Cargills with the fixed-price promotion, 3 units cost LKR 500 each and the fourth costs shelf price, and a card offer is computed on the promoted total. **Verified by** `python -m pytest tests/test_planner_promotions.py::test_fixed_price_multibuy_limit -q`.
8. Given the offers file, every Nations Trust Bank and Commercial Bank offer has `source_url`, `captured_on` 2026-10-18, `headline`, and `terms_source` "assumption", and every HNB offer is `source` "fictional". **Verified by** `python -m pytest tests/test_offers_v21.py::test_bank_offers_cite_their_source -q`.
9. Given `max_stores` 4, the planner accepts it and returns an `OPTIMAL` plan with at most 4 stores; `max_stores` 5 is rejected; given a basket where a third store saves more than the trip cost, the plan uses three stores. **Verified by** `python -m pytest tests/test_planner_promotions.py::test_up_to_four_stores -q`.
10. Given the mock endpoints, each returns `"mock": true` with the data label and the same prices and offers the engine reads; unknown ids return 404. **Verified by** `python -m pytest tests/test_mock_partners.py::test_mock_partner_endpoints_serve_the_engine_fixtures -q`.
11. Given Approve with Delivery, the page shows the assumed fee per bill, the no-integration sentence, `MOCK`, and `No order is sent.` **Verified by** `python -m pytest tests/test_v21_page.py::test_approve_offers_a_mock_delivery_quote -q`.
12. Every test passes. **Verified by** `python -m pytest -q`.
13. The README describes the v2.1 judge path. **Verified by** `python scripts/check_judge_readme.py`.

## Approved assumptions

| Id | Assumption |
| --- | --- |
| C1 | Bank offer rates use the published headline; for "up to" offers Savvy Cart applies the full headline rate to eligible items and says so. |
| C2 | Minimum bill, cap, and category limits of the real offers are not published on the listing pages; Savvy Cart keeps labeled assumption values and tells the shopper to check the bank's terms. |
| C3 | Fixed-price promotions and Cargills, SPAR, and Glomark shelf prices stay fictional demo shapes, labeled. |
| C4 | The planning window is 17 Oct 2026 (history end) to 31 Oct 2026 (end of most captured offers). |
| C5 | Suggestions look 14 days ahead (the 7-day window plus one more cycle of the shortest common cadence). |
| C6 | Delivery fee default LKR 350 per store bill is an editable assumption, not a quote from any service. |
| C7 | The inline script only submits the form when the date changes; the flow works without JavaScript. |
| C8 | Hard cut-off 17:00 Colombo time on 18 Oct 2026. Build order: date fix, wizard, real offers, four stores, multi-buy, add item, receipt upload, suggestions, mock endpoints, delivery. Whatever is not green by the cut-off is dropped and the last green build is deployed; the accepted SC-018 build is the safety net. |
| C9 | Wizard state lives in hidden form fields; no cookies and no server-side session. |
| C10 | Receipt upload is allowed on the public URL, rate limited by the existing extract limit, never stored or logged; only lines that map to a known item are kept. |
| C11 | The Plan step targets under 3 seconds locally with `max_stores` 4. |
| C12 | When a fixed-price and a percent promotion both apply to a line, the line takes the one that saves more; promotions never stack. |

## Mitigations required by the criteria

- The past-date bug stays fixed: `python -m pytest tests/test_pantry_cutoff.py -q`.
- Suggestions stay honest (own due-soon items, never auto-added, engine numbers): `python -m pytest tests/test_v21_page.py::test_offer_minimum_suggestions_use_only_items_due_soon -q`.
- Every real offer stays traceable and unpublished terms stay labeled: `python -m pytest tests/test_offers_v21.py -q`.
- Mock partners never drift from the engine's data: `python -m pytest tests/test_mock_partners.py -q`.
