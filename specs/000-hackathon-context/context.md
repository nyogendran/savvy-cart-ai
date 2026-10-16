# Hackathon context — Google Cloud AI Builder Cup 2026

Sources:

- [aibuildercup.com](https://aibuildercup.com/)
- [Themes + judging](https://aibuildercup.com/themes.html)
- [FAQs](https://aibuildercup.com/Faqs.html)
- Ask-the-Expert: [YouTube `_75UeGNj1GY`](https://www.youtube.com/watch?v=_75UeGNj1GY) (Manita Huja / Abrami Sukumaran, Google Cloud)

## Event snapshot

| Item | Detail |
| --- | --- |
| Organizer | Hack2skill (sponsored by Google Cloud) |
| Region | JAPAC |
| Team | 2–4 members (ours already formed) |
| Age | 21+ |
| Eligibility | Working professionals / entrepreneurs / startups only (no students — team-wide DQ) |
| Prize pool | USD 30,000 |
| Prototype deadline | **18 Oct 2026** (host: no extension expected) |
| Evaluation | 19 Oct – 6 Nov 2026 — **deployed URL must stay usable** |
| Finalists announced | 7 Nov 2026 |
| Grand Finale | Demo Day, Singapore — 4 Dec 2026 (only **2** travelers; visa own cost) |

## Theme (choose one)

Default hypothesis for SavvyCart: **Retail & Commerce — Intelligent Customer and Business Experiences**  
(discovery, personalization, conversational shopping, …). Confirm via `/adlc-product-strategy` before locking. Alternative if card-offer framing dominates: **BFSI**.

## Official judging weights (all themes)

| Criterion | Weight |
| --- | --- |
| Technical Merit & Gen AI Implementation | **40%** |
| Problem Alignment & Impact | **25%** |
| Innovation & Creativity | **25%** |
| User Experience & Solution Design | **10%** |

## Hard build rules

1. Google AI models (**Gemini / Gemma**) and/or agentic platforms (Agent Platform, Antigravity, AI Studio).
2. Judge-facing deploy on **Cloud Run or Firebase**.
3. Working end-to-end prototype (not deck-only).
4. English submission materials.
5. **No secrets** in GitHub / deck / video — Secret Manager or env vars only (Ask-the-Expert: DQ risk).
6. Synthetic/simulated data OK if **clearly labeled**.

## Mandatory submission pack

- [ ] Pitch deck (PDF) — problem, theme alignment, impact, feasibility, scale
- [ ] Demo video — default **≤3:00** per site/FAQ (host said ~3–4 min; prefer portal text)
- [ ] Live Cloud Run **or** Firebase URL (alive through evaluation)
- [ ] Public GitHub (or accessible) proving GenAI + GCP usage
- [ ] Description of Gemini / Firebase / Firestore / Cloud Run / Agent Platform usage

## Ask-the-Expert lessons (top-5 relevant)

- Open video with **live product**, then architecture, then impact (Abrami preference).
- Document sample questions, limits, and test path for judges.
- Dead deploy during evaluation ≈ cannot score.
- Common point loss: quiet/unclear video; strong tech that misses the problem; prototype “too thin”; feasibility doubt.
- Prefer low login friction for judges; labeled mocks OK.
- ADK 2.0 / Agent Platform recommended to show depth (not exclusive scorer).

## Official premise

Local need → build on Google Cloud → show path to **global** scale.

## Open inputs for the team

- [ ] Locked theme + official problem-statement wording from portal
- [ ] One-sentence problem
- [ ] Primary persona
- [ ] GCP project ID / billing owner
- [ ] Which 2 members travel if shortlisted
- [ ] Strategy report accepted: `specs/002-product-strategy/report.md`

## Strategy prompt

Run `/adlc-product-strategy` (or `@.cursor/prompts/adlc-product-strategy.md`) before freezing vision — optimized for **top-5 / Demo Day shortlist** odds under the 40/25/25/10 rubric.
