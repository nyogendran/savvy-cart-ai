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

## Theme (locked)

**Retail & Commerce — Intelligent Customer and Business Experiences.**

Locked 17 Oct 2026 with the narrow slice in `specs/001-product-vision/spec.md`. Card-offer rules stay inside this Retail story (personalization: this household, this card, this day). BFSI is a post-Cup adjacency, not the submitted theme.

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

## Locked 17 Oct 2026

- [x] Theme: Retail & Commerce
- [x] One-sentence problem (team-authored; portal text was not pasted — see assumptions)
- [x] Primary persona: **Karuppan** (fictional Colombo household shopper)
- [x] Strategy report accepted for the narrow slice: `specs/002-product-strategy/report.md`
- [ ] Official portal problem-statement wording (assumption A1 until pasted)
- [ ] GCP project ID / billing owner (assumption A6; do not commit the id)
- [ ] Which 2 members travel if shortlisted (assumption A7; outside the prototype)

## Approved assumptions

| Id | Assumption |
| --- | --- |
| A1 | Portal problem text was not pasted. The team sentence in the vision spec is the problem until a portal paste replaces it. |
| A2 | Deadline hour and timezone are unconfirmed. Submit before the end of **18 Oct 2026**, Asia/Colombo, with a three-hour buffer. |
| A3 | Demo video target is **≤ 3:00** unless the dashboard text the team can see differs. |
| A4 | The team is already formed, 21+, non-student, and JAPAC. This session did not re-check the Cup dashboard. |
| A5 | Gemini model id is chosen at build time. It must accept an image and a JSON schema. Region is `asia-southeast1` when that model is callable there; otherwise the region that succeeds, written in the README. |
| A6 | A GCP project with billing is a human prerequisite. The project id stays out of git. |
| A7 | Finale travelers are undecided and are not part of this prototype. |
| A8 | Fixture prices are fictional. Offer geometry copies public term patterns and is not a live promotion or a bank affiliation. |
| A9 | Karuppan’s buying pattern is a static staple fixture, not a trained forecast. |
| A10 | Firestore and Cloud Storage are optional. Committed fixture JSON is enough to meet acceptance. |

## Strategy prompt

Run `/adlc-product-strategy` (or `@.cursor/prompts/adlc-product-strategy.md`) before freezing vision — optimized for **top-5 / Demo Day shortlist** odds under the 40/25/25/10 rubric.
