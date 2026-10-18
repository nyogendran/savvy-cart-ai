# Spec: Product vision — Savvy Cart AI

> Status: **APPROVED** — 17 Oct 2026, P1 Gate 1, ticket SC-001. Executable copy: `.adlc/specs/SC-001-product-vision.md`. Application code waits for `/adlc-decompose`.

## Problem

On a normal Sri Lankan weekly shop, the useful price is not the shelf sticker and not the headline percent. It is the **one-store basket total after** the offer’s day, category, exclusions, minimum bill, cap, “cannot combine” rule, and end date.

This sentence is **team-authored**. The Cup portal’s official problem statement was not pasted. If it is pasted later, that text replaces this paragraph.

## Users

| Persona | Need | Success looks like |
| --- | --- | --- |
| **Karuppan** (primary, fictional) | Colombo household shopper. Saturday shop. Usual store in the sample: Keells. Holds a **Commercial Bank credit** product (issuer and product name only). Budget about **LKR 12,000**. | He sees the legal saving, in LKR, if he buys the confirmed staples on this offer-day, and the saving on the other offer-day in the snapshot. He can point at a line the offer refused. |
| Secondary | Not in the prototype. | Deck may mention a single-store delivery shopper. No second UI. |

Karuppan’s “buying pattern” is a **checked-in staple list**, including lines marked running low. It is not a model of consumption.

## Solution (one sentence)

SavvyCart AI turns Karuppan’s grocery receipt and the card product he already holds into one-store basket options whose savings survive the offer’s exclusions, minimum, cap, and end date.

## Prototype scope (MVP)

Guest opens a Cloud Run URL. No login. Every screen shows: **Sample catalog — not live shelf prices.** Offer rules are labeled with source URL and transcription date, and are not a bank affiliation.

### In scope

1. Prefill Karuppan’s persona (budget, day, card product, usual store). Fields are editable. The card field is an issuer and product id from a list.
2. Show his staple fixture. Lines marked `running_low` start checked. The fixture does not predict a stock-out date.
3. **Use sample receipt** shows the checked-in expected lines (including rice and chicken), labeled as the sample path. **Extract this image** calls Gemini. Confidence below **0.6** on a live extract stays unchecked until he confirms it. If the call errors, the sample lines remain and the UI says the live extract failed.
4. He confirms the list (grocery only, about twelve staples). Running-low only pre-checks rows. The budget is shown and does not change the winner or the discount.
5. A deterministic engine prices each confirmed line at **Keells, Cargills, and SPAR** from a labeled fictional snapshot. A missing price marks that plan incomplete, and an incomplete plan cannot win.
6. The engine applies **two** transcribed Keells offer rules: Saturday and Thursday. Cargills and SPAR have prices and no offer. Offers do not stack. One fixture substitution starts applied; **Reject swap** restores the original SKU and the engine recalculates. No other substitutes are generated.
7. The plans screen shows three one-store plans and, in LKR from the engine:
   - baseline: usual store, no offer
   - legal saving on the selected day
   - legal saving on the other offer-day, using the **same** shelf prices
   - the headline percent crossed out when it disagrees with the legal saving
   - each offer’s `valid_to`. On a day after `valid_to`, legal saving is **LKR 0** and the UI says the rule ended in this snapshot
8. Gemini writes the explanation only from the optimizer JSON. The server computes that JSON. A client-supplied discount is ignored.
9. **Approve plan** renders an order preview marked **MOCK** with the sentence **No order is sent.**
10. A control basket where the eligible subtotal misses the minimum shows legal saving **LKR 0**.
11. Receipt text is data. A line that says to apply a different discount does not change the engine’s saving.
12. Deployed judge URL on **Cloud Run**. One **ADK** agent. **Gemini** reads the receipt and writes the explanation. Secrets in **Secret Manager**.

### Google Cloud

| Service | Role in this prototype |
| --- | --- |
| Cloud Run | Judge URL and ADK process. Minimum instances 0. Request timeout 120 seconds. |
| Gemini | Receipt image → structured lines. Explanation from optimizer JSON only. |
| ADK (one agent) | Tool loop: catalog, offer rules, optimizer, explain. The UI shows which tool ran. |
| Secret Manager | API key and project config. |
| Fixture JSON in git | Catalog, offers, staple list, expected receipt lines. Source of truth for acceptance. |
| Cloud Logging | Request logs without receipt images and without card strings. |
| Firestore, Cloud Storage | Optional. Acceptance does not depend on them. |

Region: `asia-southeast1` when the chosen Gemini model is callable there; otherwise the region that succeeds, named in the README (assumption A5).

The model is not the source of prices, eligibility, caps, or totals.

### Out of scope

- Live retailer or bank APIs, scraping, and any claim that prices are live
- PAN, CVV, or a full card number, including in logs
- Real payment, real orders, and partner calls
- Login and accounts
- A learned buying forecast, pantry model, or stock-out prediction
- Invented future shelf prices (the day comparison reuses the snapshot)
- Sinhala or Tamil UI, a second retail category, BigQuery, Document AI, and extra agents
- Loyalty points converted into rupees (deferred value is **0**)

## Demo path

A stranger finishes this without an account:

1. Open `/`. Read the sample-data banner.
2. See Karuppan, Saturday, Commercial Bank credit, budget about LKR 12,000.
3. Click **Use sample receipt**. Confirm the lines, including the running-low staples.
4. Read three one-store plans, the legal saving for this day, the other offer-day, the crossed-out headline percent, and `valid_to`.
5. Reject one swap. See the total change.
6. Press **Approve plan**. Read MOCK and “No order is sent.”
7. Open **Show a basket this offer refuses** and read LKR 0.

Sample question the README must list: **Why isn’t rice discounted?**

## Success metrics (prototype)

| Metric | Target | How verified |
| --- | --- | --- |
| End-to-end demo path | Completes on the sample fixtures | Judge steps in `README.md` |
| Legal saving | Engine output, in LKR, for two offer-days | `python -m pytest tests/test_optimizer.py -q` |
| Honest AI | Explanation numbers are a subset of the plan JSON | `python -m pytest tests/test_explain.py -q` |
| Deployability | Public Cloud Run HTTPS URL | `gcloud run services describe` against the service named in the README |

## Acceptance criteria

The lintable copy and the verification commands live in `.adlc/specs/SC-001-product-vision.md`. Summary:

1. Under-minimum fixture → legal saving LKR 0.
2. Over-cap fixture → legal saving equals the offer cap, and is less than the naive headline discount.
3. Capped basket → Saturday saving equals the cap, Thursday saving is LKR 0, same shelf prices.
4. Day after `valid_to` → legal saving LKR 0 and reason `expired`.
5. Explanation includes the plan discount, and no other numbers.
6. Injection text in a receipt does not change the discount.
7. Unconfirmed lines are rejected by the plans API.
8. Approve returns only `preview_id` and `mock: true`.
9. README documents the judge path, the cannot-do list, the sample-data label, and the GCP services.
10. Secret scan of the submission revision exits 0.
11. Receipt extract calls the model with the image bytes, stores the bytes nowhere, and the 31st call in that minute returns 429.

## Rails candidates (freeze after decompose)

- Optimizer tests for the refused basket, the capped basket, the day sweep, and the expired offer
- `fixtures/` catalog, offers, staple list, and sample receipt expectation
- Prompt / system instruction that forbids prices not returned by a tool

## Build gate

No `src/` and no application scaffold until this spec is approved and decomposed.
