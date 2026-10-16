# Savvy Cart AI

Prototype for the [Google Cloud AI Builder Cup 2026](https://aibuildercup.com/) — built with a **spec-driven Agentic Development Lifecycle (ADLC)**.

## Start here (ADLC)

1. Install the gate CLI: `npm i -g @adlc/cli`
2. In Cursor, open a new chat and attach / run:

   **`.cursor/prompts/adlc-kickoff.md`**

3. Follow the agent through P0 → P1 until you explicitly approve the vision spec.
4. Then continue with `/adlc-decompose` → build → `/adlc-verify-build` → `/adlc-prosecute`.

Details: [`docs/adlc/WORKFLOW.md`](docs/adlc/WORKFLOW.md) · [`AGENTS.md`](AGENTS.md)

## Repo map

```text
.adlc/                 # ADLC runtime (tickets, gate evidence)
.cursor/
  commands/            # /adlc-* slash commands
  prompts/             # Kickoff + reusable prompts
  rules/               # Always-on + phase routing rules
specs/                 # Constitution, hackathon context, product vision
docs/adlc/             # Human-readable workflow
```

## Status

- ADLC workspace initialized (`adlc init --harness cursor`)
- Cursor hooks, rules, and `/adlc-*` commands deployed
- Product vision + constitution drafted — **awaiting kickoff interrogation**

Application code will land only after the first approved spec.
