# Spec: Product vision — Savvy Cart AI

> Status: **DRAFT** — complete open questions, then run `/adlc-spec` and `/adlc-approve-spec`.

## Problem

*(Fill)* Shoppers waste time and money because carts lack intelligent guidance on price, substitutes, dietary/budget constraints, and checkout readiness.

## Users

| Persona | Need | Success looks like |
| --- | --- | --- |
| Primary *(TBD)* | | |
| Secondary *(optional)* | | |

## Solution (one sentence)

Savvy Cart AI uses Google Cloud AI to turn a shopping cart into a guided decision surface — recommending, explaining, and validating items against user constraints.

## Prototype scope (MVP)

### In scope

1. User can create/view a cart (or import a sample cart).
2. User can state constraints (budget, diet, brand preference) in natural language.
3. System calls **Vertex AI / Gemini** with cart + constraints and returns structured advice.
4. UI shows recommendations with **source/confidence** (no silent hallucinations).
5. Deployed or clearly runnable on **Google Cloud** (Cloud Run or equivalent).

### Out of scope (this hackathon)

- Real payment capture
- Full retailer integrations beyond one sample catalog / mock feed
- Native mobile apps
- Multi-language launch (English first unless problem statement requires otherwise)

## Success metrics (prototype)

| Metric | Target | How verified |
| --- | --- | --- |
| End-to-end demo path | Completes in ≤ 5 minutes | Demo script dry-run |
| AI response grounded | Advice references cart items present in context | Manual checklist + sample fixture |
| Deployability | App reachable via public HTTPS or `gcloud run services describe` | CLI command |

## Acceptance criteria (must be lintable)

1. Given fixture cart `fixtures/sample-cart.json`, when the user asks for budget-fit advice, the API returns JSON matching the documented schema **verified by** `npm test -- advice.schema` *(or equivalent once scaffolded)*.
2. Given an empty cart, the UI shows a blocking empty state and does not call the model **verified by** Playwright/Cypress assertion *(or manual script step listed in demo.md)*.
3. README documents GCP services used and one-command local run **verified by** link check in PR description.

## Open questions (resolve in P1)

1. Exact problem statement / track from the Cup portal?
2. Single-retailer vs retailer-agnostic catalog for the demo?
3. Auth required for demo, or guest mode OK?
4. Preferred GCP region (e.g. `asia-southeast1` for Singapore narrative)?

## Rails candidates (freeze after decompose)

- Contract tests for advice JSON schema
- Fixture carts used in demo
- Prompt template / system instruction file (once stable)
