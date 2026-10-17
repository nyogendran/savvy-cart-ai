# Savvy Cart AI

A Colombo household holds three credit cards and shops at four supermarket chains. Every chain runs item promotions, and every bank runs card offers tied to one store, one weekday, a category, a minimum bill, and a cap. The household cannot tell when the staples will run out, which store and card to use for which items, or what a promotion really saves. Savvy Cart AI reads the purchase history, lists what is running low, and plans the cheapest way to buy it on a chosen day: up to two stores, one card per bill, every rule applied in code. Then the shopper decides.

The evidence is one real shopper's 26 Keells e-bills (5 May to 17 Oct 2026, de-identified): promotions were item-level, not bill-wide, and on four days the shopper paid at more than one store.

Built for the [Google Cloud AI Builder Cup 2026](https://aibuildercup.com/), Retail & Commerce theme.

**Sample catalog — not live shelf prices.** Keells prices come from that shopper's real receipts. Cargills, SPAR, and Glomark prices stay within 10% of Keells and are fictional, and so is every card offer and store promotion.

## Judge path (about three minutes, no login)

Open the judge URL. The first load can take tens of seconds while Cloud Run starts an instance from zero. The page is one guided flow: **Pantry, Wallet, Plan, Why, Approve**. The sample-data banner stays on every step.

1. **Pantry.** The planning date is a demo control set to Thursday 22 Oct 2026, because the history ends on 17 Oct. From the usual gap between purchases and the last purchase date, the pantry lists 12 items as due or soon, each with its reason, for example "Bought on 17 days, about every 8 days. Last bought 17 Oct, so due 25 Oct (in 3 days)." No model guesses this. Tea bun is overdue by more than its own cycle, so it is marked "Not bought for a while" and starts unchecked.
2. Press **Use sample receipt** to add a redacted Keells receipt to the history, dated on the planning day. The list drops from 12 to 9: eggs, milk, and yoghurt were just bought, and bananas and dish wash move their due dates later. **Extract this image** sends the same redacted photo to Gemini when a model is configured.
3. **Wallet.** Karuppan holds Commercial Bank, Nations Trust Bank, and HNB credit cards, shown as issuer and product only. Choose the cards, the usual store, at most one or two stores, and the cost of an extra trip (LKR 250 by default, labeled an assumption).
4. **Plan.** Press **Plan my shopping**. An exact optimizer (Google OR-Tools CP-SAT) assigns every checked item to a store, applies store promotions first, then picks at most one card offer per bill. On the default inputs the cheapest plan is Glomark with Nations Trust Bank credit, LKR 4,660, which is LKR 1,280 less than buying everything at Keells at shelf price. The page shows each store bill line by line, both baselines (usual store at shelf price, best single store), and the best day to shop before items run out.
5. Press **Show a basket this offer refuses**. A small Saturday basket at Keells misses both Keells card minimums, the card discount is LKR 0, and the page says how far each offer was from paying.
6. **Why.** Press **Explain this plan**. The one ADK agent explains the plan and may re-plan, for example to compare another day or a smaller wallet. The page lists every tool it called with its arguments and says plainly when it re-planned with different inputs. Any number in the answer that no engine output produced is dropped before it is shown. If no model is configured, or the agent call fails, the page says so and shows the engine's own explanation.
7. **Approve.** Press **Approve plan**. The page shows a MOCK order preview. No order is sent.

## The original single-store API

The first slice, a single-store offer checker, still runs unchanged at `POST /v1/plans`, `POST /v1/explain`, `POST /v1/receipts`, and `POST /v1/approve`. Its sample shopper is **Karuppan, Saturday, Commercial Bank credit, budget about LKR 12,000.** It answers one question the guided flow builds on:

- **Why isn’t rice discounted?** Rice is a staple. That card offer covers fresh items only, so rice stays at shelf price in every plan.

## How it works on Google Cloud

| Piece | Role |
| --- | --- |
| Cloud Run | Serves the guided flow and the API. Minimum instances 0. |
| Gemini on Agent Platform | Gemini runs on Gemini Enterprise Agent Platform (formerly Vertex AI). It reads receipt images into structured lines and, through the agent, explains the plan from engine output. The Cloud Run service account authenticates, so no API key exists in the default deploy. |
| Agent Development Kit | One agent, `root_agent`, with tools for the pantry, catalog, offers, day planner, and explanation numbers. It can call the planner again with other inputs. |
| Secret Manager | Holds the Gemini model configuration, mounted into Cloud Run at deploy time. Nothing secret is in this repo. |

The model is never the source of a price, a discount, a due date, or a total. Deterministic code computes every rupee and every date.

Receipt images are not written to disk, storage, or logs, and extraction is rate limited. If the live call fails, the page says so and keeps the sample lines.

## Cannot do

This prototype does not provide:

- live prices or live stock from any retailer
- real orders, payments, or partner checkout (approve is a MOCK preview)
- card numbers: it never asks for, stores, or logs a card number, only an issuer and product
- bank affiliation: the offers are fictional demo shapes, and Savvy Cart AI is not affiliated with or endorsed by Commercial Bank, Nations Trust Bank, HNB, or any retailer
- forecasting beyond the purchase gaps: due dates come from the median gap between purchases, not a trained model

## Run it locally

```bash
pip install -e ".[dev]"
python -m pytest -q
uvicorn savvycart.http:app --reload
```

Open http://127.0.0.1:8000/. Without a configured model the whole flow works: **Extract this image** reports that the live extract failed, and **Explain this plan** shows the engine explanation.

`samples/purchase-history.json` is built from the shopper's e-bill PDFs by `scripts/build_history.py`. The PDFs stay on the shopper's machine and are never committed. Only dates, chains, line items, amounts, and promotions are kept.

## How this was built

Spec-driven, with the [Agentic Development Lifecycle](https://www.agenticlifecycle.ai/) (ADLC): an approved spec, small tickets with verifiable acceptance criteria, frozen rails, and a hostile review before each slice is accepted. See [`AGENTS.md`](AGENTS.md) and [`docs/adlc/WORKFLOW.md`](docs/adlc/WORKFLOW.md).
