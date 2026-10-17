# Savvy Cart AI

A Sri Lankan supermarket "25% off" card offer almost never means 25% off the trolley. Staples are excluded, the bill has to clear a minimum, and a cap eats the rest. Savvy Cart AI reads a receipt, prices the basket at three stores, applies the published offer rule in code, and shows the rupees that actually remain. Then the shopper decides.

Built for the [Google Cloud AI Builder Cup 2026](https://aibuildercup.com/), Retail & Commerce theme.

**Sample catalog — not live shelf prices.**

## Judge path (about three minutes, no login)

Open the judge URL. The first load can take tens of seconds while Cloud Run starts an instance from zero.

1. Read the banner. Every price on the page comes from a labeled fictional snapshot.
2. The shopper is prefilled: **Karuppan, Saturday, Commercial Bank credit, budget about LKR 12,000.** Weekday, usual store, and budget are editable. The card field is an issuer and product id, never a card number.
3. Press **Use sample receipt**. The receipt lines (rice, chicken, milk powder, vegetables) load as fixture lines for the sample path. Running-low staples start checked.
4. Read three one-store plans: Keells, Cargills, and SPAR. Look for:
   - the card headline percent crossed out, next to the legal saving the engine computed
   - the legal saving on the other offer day, on the same shelf prices
   - each offer's `valid_to`
   - the tool trail: catalog, offers, optimizer
5. Read **Your options**. The page applies one cheaper substitute (budget chicken), which drops the fresh items below the offer minimum, so the offer pays 0. Option B restores the original chicken, meets the minimum, and earns the capped saving. The page shows both totals and says which one costs less. It never adds items to reach a minimum. Press **Reject swap** to choose Option B, or **Keep swap** to go back.
6. Press **Approve plan**. The page shows a MOCK order preview. No order is sent.
7. Press **Show a basket this offer refuses**. The eligible subtotal misses the minimum, and the legal saving is LKR 0.

Two questions the plans answer:

- **Why isn’t rice discounted?** Rice is a staple. The card offer covers fresh items only, so rice stays at shelf price in every plan.
- **Why does the cheaper basket get no card saving?** The budget chicken brings the fresh items under the offer minimum. Below the minimum the offer pays nothing.

The explanation API, `POST /v1/explain`, has Gemini write from the optimizer's JSON only. Any number the model invents is dropped, and if the model call fails the engine's own sentence is returned. The guest page does not show this explanation yet.

## How it works on Google Cloud

| Piece | Role |
| --- | --- |
| Cloud Run | Serves the guest page and the API. Minimum instances 0. |
| Gemini | Reads the receipt image into structured lines. Writes the plan explanation from the plan JSON through the explain API. |
| Agent Development Kit | One agent, `root_agent`, with four tools: catalog, offers, optimizer, explain. The guest page calls the same functions directly, and its tool trail lists them. |
| Secret Manager | Holds the model API key and configuration. Nothing secret is in this repo. |

The model is never the source of a price, a discount, or a total. A deterministic optimizer computes every rupee.

**Extract this image** sends a receipt photo to Gemini when the service is configured with a model and key. Images are not written to disk, storage, or logs, and extraction is rate limited. If the live call fails, the sample lines stay and the page says so.

## Cannot do

This prototype does not provide:

- live prices or live stock from any retailer
- real orders, payments, or partner checkout (approve is a MOCK preview)
- card numbers: it never asks for, stores, or logs a card number, only an issuer and product id
- bank affiliation: the offer rules are transcribed demo shapes, and Savvy Cart AI is not affiliated with or endorsed by Commercial Bank or any retailer
- purchase-history tracking or stock-out prediction

## Run it locally

```bash
pip install -e ".[dev]"
python -m pytest -q
uvicorn savvycart.http:app --reload
```

Open http://127.0.0.1:8000/. Without a configured model, the sample path works fully and **Extract this image** reports that the live extract failed.

## How this was built

Spec-driven, with the [Agentic Development Lifecycle](https://www.agenticlifecycle.ai/) (ADLC): an approved spec, small tickets with verifiable acceptance criteria, frozen rails, and a hostile review before each slice is accepted. See [`AGENTS.md`](AGENTS.md) and [`docs/adlc/WORKFLOW.md`](docs/adlc/WORKFLOW.md).
