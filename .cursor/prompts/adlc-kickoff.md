---
description: >-
  Start the Spec-Driven Agentic Development Lifecycle for Savvy Cart AI
  (Google Cloud AI Builder Cup). Run this prompt first in a new chat.
---

# ADLC Kickoff — Savvy Cart AI

You are bootstrapping **Savvy Cart AI** for the [Google Cloud AI Builder Cup](https://aibuildercup.com/) using the **Agentic Development Lifecycle (ADLC)**.

## Your job in this session

Run **P0 → P1 only**. Do **not** write application source code yet (no `src/`, no scaffolding frameworks) until the product-vision spec is approved.

### Step 0 — Orient

1. Read:
   - `AGENTS.md`
   - `specs/constitution.md`
   - `specs/000-hackathon-context/context.md`
   - `specs/001-product-vision/spec.md`
   - `specs/002-product-strategy/report.md` if it exists (from `/adlc-product-strategy`)
   - `.cursor/rules/adlc.mdc`
2. Confirm `@adlc/cli` is usable (`adlc --help`). If missing, tell me to run `npm i -g @adlc/cli`.
3. Run `adlc preflight` (or summarize what I should run) and report pass/fail.

### Step 1 — Interrogate (human gate prep)

Using the shared ADLC interrogation style:

- Ask **numbered questions**, one recommended answer first.
- Only ask what the repo cannot already answer.
- Cap at **5 rounds**; anything left becomes **approved assumptions** written into the vision spec.
- Prioritize: problem statement from the Cup portal, persona, MVP slice, GCP services, demo path, what’s explicitly out of scope.

Update these files with my answers (do not invent Cup problem-statement text):

- `specs/000-hackathon-context/context.md` (checkboxes + chosen challenge)
- `specs/001-product-vision/spec.md` (problem, users, MVP, ACs)
- `specs/constitution.md` only if a principle must change

### Step 2 — Author the first ticket (P0)

Create ticket `SC-001` (or next free id) via `adlc ticket` for:

> Freeze product vision + MVP acceptance criteria so we can decompose and build a GCP-backed prototype before **18 Oct 2026**.

Requirements for the ticket body:

- Self-contained context (Cup deadline, Google Cloud constraint, Savvy Cart mission)
- Acceptance criteria with **concrete verification**
- Suggested `scope` globs limited to `specs/**`, `.adlc/specs/**`, `docs/**`, `README.md`
- `rails: []` for now

Dry-run first; apply with `--write` only after I accept.

### Step 3 — Spec gate (P1)

1. Write the working executable spec under `.adlc/specs/SC-001-product-vision.md` (derived from `specs/001-product-vision/spec.md`).
2. Run (prefer `--prompt-only` inside Cursor; you answer the printed prompts):
   - `adlc parallax …`
   - `adlc premortem …`
   - `adlc spec-lint …`
3. Fold findings into the spec; remove vacuous ACs.
4. Stop at **`/adlc-approve-spec`** — ask me to explicitly approve before any `/adlc-decompose` or code.

## Constraints

- Follow `specs/constitution.md`.
- Optimize for a **demoable vertical slice**, not a full product.
- Prefer Google Cloud (Vertex AI / Gemini, Cloud Run, managed data).
- Never commit secrets.
- If I paste the official challenge text, treat it as source of truth over placeholders.

## Output format each turn

1. **Phase:** P0 | P1 | blocked
2. **What changed** (file list)
3. **Questions for me** (numbered, with recommended answers)
4. **Next command** I should run or approve (`/adlc-approve-spec`, etc.)

Begin with Step 0, then ask Round 1 questions.
