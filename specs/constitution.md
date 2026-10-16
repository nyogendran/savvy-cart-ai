# Constitution — Savvy Cart AI

Immutable principles for every ADLC ticket, spec, and build. Update only with explicit team consensus.

## 1. Mission

Build **Savvy Cart AI**: an AI-assisted shopping experience that helps people make smarter cart decisions (price, substitutes, constraints, and checkout confidence) — starting from a local JAPAC need, designed to scale globally.

## 2. Non-negotiables

1. **Spec before code.** No feature implementation without an approved ticket + linted spec (P1 G1).
2. **Demoable vertical slice.** Every milestone must leave a user-visible path that can be shown live.
3. **Google Cloud first.** Prefer Vertex AI / Gemini, Cloud Run, Firestore/AlloyDB/BigQuery, Cloud Storage, Identity Platform / Firebase Auth, and Cloud Logging — document any exception in the ticket body.
4. **Verifiable done.** Acceptance criteria name a command, test, or observable assertion.
5. **Secrets stay out of git.** Use Secret Manager / env; never commit keys.
6. **Honest AI.** Surface uncertainty; never invent prices, inventory, or policy claims without a data source.
7. **Privacy & safety.** Minimize PII; no logging of payment details; refuse harmful shopping intents.

## 3. Prototype constraints (AI Builder Cup)

- **Team size:** 2–4 (already formed).
- **Submission deadline:** 18 Oct 2026.
- **Region:** JAPAC; in-person finale Singapore if shortlisted.
- **Stack bias:** working prototype on Google Cloud addressing a chosen problem statement.
- **Audience:** working professionals (eligibility already assumed).

## 4. Quality bar for prototype

| Must ship | Nice-to-have (post-MVP tickets) |
| --- | --- |
| Clear problem → solution narrative | Full multi-tenant SaaS |
| End-to-end happy path on GCP | Perfect UX polish |
| At least one Gemini/Vertex AI call with grounded context | Offline/edge modes |
| README + demo script | Exhaustive test suite |

## 5. Decision defaults

When the agent would otherwise guess:

- Prefer **managed GCP services** over self-hosted.
- Prefer **one** primary user persona for the prototype.
- Prefer **read-heavy** AI assistance over write-heavy automation that can harm carts/wallets.
- Prefer **structured outputs** (JSON schema) from models for anything that drives UI state.
