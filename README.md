# Savvy Cart AI

A Colombo household holds three credit cards and shops at four supermarket chains. Every chain runs item promotions, and every bank runs card offers tied to one store, one weekday, a category, a minimum bill, and a cap. The household cannot tell when the staples will run out, which store and card to use for which items, or what a promotion really saves. Savvy Cart AI reads the purchase history, lists what is running low, and plans the cheapest way to buy it on a chosen day: up to four stores, one card per bill, every rule applied in code. Then the shopper decides.

The trap is the headline. A bank SMS says "10% off on Total Bill every Saturday"; the terms behind it exclude rice, milk powder, and dhal, need an LKR 8,000 bill, stop at LKR 1,000, and cannot be combined with the store's own promotions. **Offer Reality Check** lets the shopper paste such an offer: Gemini reads the terms, the shopper confirms them, and the engine shows what the headline promises against what the terms pay on that household's basket.

The evidence is one real shopper's 26 Keells e-bills (5 May to 17 Oct 2026, de-identified): promotions were item-level, not bill-wide, and on four days the shopper paid at more than one store. The demo pantry adds 17 fictional Cargills and Glomark bills, labeled on every page. Every saving the app shows is simulated on sample data.

Built for the [Google Cloud AI Builder Cup 2026](https://aibuildercup.com/), Retail & Commerce theme.

**Sample catalog — not live shelf prices.** Keells prices come from that shopper's real receipts. Cargills, SPAR, and Glomark prices stay within 10% of Keells and are fictional. Nations Trust Bank and Commercial Bank card offers are their published supermarket headlines, captured from the banks' promotion pages on 18 Oct 2026; their minimum bills and caps are not published there, so those are labeled assumptions. HNB offers and every store promotion are fictional demo shapes.

## Judge path (about three minutes, no login)

Open the judge URL. The first load can take tens of seconds while Cloud Run starts an instance from zero. The page is a five-step wizard, one step at a time: **Pantry, Wallet, Plan, Why, Approve**, with Back and Next on every step. The sample-data banner stays on every step; press **What is real in this demo?** for what is real and what is fictional. A card for Karuppan's household (a fictional demo profile) sits above the steps and shows the current budget, cards, and usual store.

1. **Pantry.** **Planning date** is set to Thursday 22 Oct 2026; it offers 17 to 31 Oct because the sample history ends on 17 Oct, and only purchases up to that date count. From the usual gap between purchases and the last purchase date, the pantry lists 12 items as due or soon, each with a short label such as "Due in 3 days"; open the label for the reason, for example "Bought on 17 days, about every 8 days. Last bought 17 Oct, so due 25 Oct (in 3 days)." No model guesses this. Quantities respect how an item is sold: packs and cartons are whole numbers (a 2-pack of buns is never 2.5), and produce priced by weight is planned in half kilos (carrots 0.5 kg). Tea bun is overdue by more than its own cycle, so it is marked "Not bought for a while" and starts unchecked. **Add an item** puts any other catalog item in the basket.
2. Press **Use sample receipt** to add a redacted Keells receipt to the history, dated on the planning day. The page lists the lines it added, and the list drops from 12 to 9: eggs, milk, and yoghurt were just bought. **Upload a receipt photo** sends your own JPEG or PNG to Gemini when a model is configured; Gemini matches each line to the catalog, so receipts from any of the four chains work, and loose produce keeps its weight in the history (0.375 kg stays 0.375, while the pantry plans the next buy in half kilos). A line that matches no known item description and that Gemini is less than 60% sure of is left out. The photo is never stored.
3. **Wallet.** Karuppan holds Commercial Bank, Nations Trust Bank, and HNB credit cards, shown as issuer and product only. Choose the cards, the usual store, up to four stores in one day, and the cost of an extra trip (LKR 250 by default, labeled an assumption).
   - **Check a card offer.** Press **Use the sample offer**: Seylan Bank's published Keells terms, checked on seylan.lk on 18 Oct 2026. The headline suggests LKR 593 off this basket; the terms pay **LKR 0** (shown in amber), because the bill is LKR 2,475 short of the LKR 8,000 minimum, and six items on a store promotion would not count anyway. The page lists every line with the reason it counts or not, notes that the terms also exclude the milk powder and dhal this household buys, and shows the engine's best plan if Karuppan held that card. **Read it with Gemini** reads pasted text or a screenshot into a fixed schema; code validates every field and never invents a minimum, cap, or percent; the shopper can correct the terms and recheck. Savvy Cart is not affiliated with Seylan Bank.
4. **Plan.** Press **Next: plan my shopping**. An exact optimizer (Google OR-Tools CP-SAT) assigns every checked item to a store, applies the store promotion that saves most on each line (a percent off, or a fixed price for up to a number of units), then picks at most one card offer per bill. On the default inputs the page opens with its recommendation, "Shop on Friday 23 Oct at Keells and Cargills. Pay with Commercial Bank credit at Cargills." (its published "up to 25%" Friday offer): LKR 4,604 including the extra trip, which is LKR 1,328 less than buying everything at Keells at shelf price. The page shows each bill line by line with quantities and unit prices, the offer's published headline and source when it is a real bank offer, both baselines (the two-store split beats the best single store by only LKR 63, and raising the trip cost to LKR 320 makes the engine drop the second store), and the best day to shop before the estimated next purchase date. When a card offer misses its minimum, the page may suggest up to three items you need within 14 days that would reach it, with the engine's re-planned total; it never adds them, and says so when nothing you need would reach it.
5. On the Wallet step, press **Show a basket this offer refuses**. A small Saturday basket at Keells misses the Commercial Bank minimum, the card discount is LKR 0, and the page says how far the offer was from paying.
6. **Why.** Press **Next: explain this plan**. The one ADK agent explains the plan and may re-plan, for example to compare another day or a smaller wallet. Ask your own question, or press a sample one such as "What if I only use my Commercial Bank card?"; the agent turns it into planner calls, and it can call `check_card_offer` to price an offer you describe against your basket. Its pantry tool sees receipts added in this session. Open **How this was calculated** to see every tool it called with its arguments; the page says plainly, outside that block, when it re-planned with different inputs, and that HNB offers are fictional. Grounding runs in two layers: ADK callbacks inside the agent keep it within the planning window and strip ungrounded numbers, and the page re-checks on the way out. Any number in the answer that no engine output produced is dropped before it is shown, and so is a sentence that calls the plan total a saving or the saving a total. If no model is configured, the agent call fails, or the service has reached its limit of 20 explanations a minute, the page says so and shows the engine's own explanation.
7. **Approve.** Choose Pickup or Delivery (MOCK). Delivery adds an assumed fee per store bill (LKR 350, editable) and says that no booking is made and Savvy Cart is not integrated with Uber, PickMe, or any store. The page shows a MOCK order preview. No order is sent.

Mock partner endpoints, `GET /mock/stores`, `GET /mock/stores/{store_id}/catalog`, `GET /mock/banks`, and `GET /mock/banks/{bank_id}/offers`, serve the same labeled data the engine reads, the way store and bank APIs would.

## The original single-store API

The first slice, a single-store offer checker, still runs unchanged at `POST /v1/plans`, `POST /v1/explain`, `POST /v1/receipts`, and `POST /v1/approve`. Its sample shopper is **Karuppan, Saturday, Commercial Bank credit, budget about LKR 12,000.** It answers one question the guided flow builds on:

- **Why isn’t rice discounted?** Rice is a staple. That card offer covers fresh items only, so rice stays at shelf price in every plan.

## How it works on Google Cloud

| Piece | Role |
| --- | --- |
| Cloud Run | Serves the guided flow and the API. Minimum instances 0. |
| Gemini on Agent Platform | Gemini runs on Gemini Enterprise Agent Platform (formerly Vertex AI). It reads receipt images into catalog-matched lines, reads bank offer text or screenshots into structured terms, and, through the agent, answers the shopper's questions from engine output. The Cloud Run service account authenticates, so no API key exists in the default deploy. |
| Agent Development Kit | One agent, `root_agent`, with tools for the pantry, catalog, offers, day planner, and explanation numbers. It can call the planner again with other inputs. |
| Secret Manager | Holds the Gemini model configuration, mounted into Cloud Run at deploy time. Nothing secret is in this repo. |

The model is never the source of a price, a discount, a due date, or a total. Deterministic code computes every rupee and every date.

Receipt images are not written to disk, storage, or logs, and extraction is rate limited. If the live call fails, the page says so and keeps the sample lines.

## Cannot do

This prototype does not provide:

- live prices or live stock from any retailer
- real orders, payments, or partner checkout (approve is a MOCK preview)
- card numbers: it never asks for, stores, or logs a card number, only an issuer and product
- bank affiliation: two banks' published offer headlines are shown with their source and assumed terms, HNB offers are fictional, and Savvy Cart AI is not affiliated with or endorsed by Commercial Bank, Nations Trust Bank, HNB, or any retailer
- delivery or partner integrations: the delivery option and the partner endpoints are mocks
- forecasting beyond the purchase gaps: due dates come from the median gap between purchases, not a trained model

## Run it locally

```bash
pip install -e ".[dev]"
python -m pytest -q
uvicorn savvycart.http:app --reload
```

Open http://127.0.0.1:8000/. Without a configured model the whole flow works: **Upload a receipt photo** says the live extract is unavailable, and **Next: explain this plan** shows the engine explanation.

`samples/purchase-history.json` is built from the shopper's e-bill PDFs by `scripts/build_history.py`. The PDFs stay on the shopper's machine and are never committed. Only dates, chains, line items, amounts, and promotions are kept.

## How this was built

Spec-driven, with the [Agentic Development Lifecycle](https://www.agenticlifecycle.ai/) (ADLC): an approved spec, small tickets with verifiable acceptance criteria, frozen rails, and a hostile review before each slice is accepted. See [`AGENTS.md`](AGENTS.md) and [`docs/adlc/WORKFLOW.md`](docs/adlc/WORKFLOW.md).
