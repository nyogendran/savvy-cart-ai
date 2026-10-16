# Savvy Cart AI — Agent Operating Manual

This repo uses the **Agentic Development Lifecycle (ADLC)**: specs and tickets are the source of truth; code follows gates.

## Hard rules

1. **Do not skip gates.** Spec → approve → decompose → rail → build → prosecute → integrate.
2. **Human gates are mandatory** at P1 (spec approval) and P6 (behavioral acceptance).
3. **Acceptance criteria must be verifiable** (command, test, or observable assertion). No wishes.
4. **Prefer Google Cloud** for AI, data, and deploy surfaces (AI Builder Cup requirement).
5. **Prototype deadline: 18 Oct 2026.** Optimize for a demoable slice; park non-MVP work as follow-up tickets.

## Where truth lives

| Artifact | Path |
| --- | --- |
| Runtime / tickets | `.adlc/` |
| Feature specs | `.adlc/specs/` |
| Constitution | `specs/constitution.md` |
| Product vision | `specs/001-product-vision/spec.md` |
| Hackathon context | `specs/000-hackathon-context/context.md` |
| Product strategy report | `specs/002-product-strategy/report.md` |
| Phase commands | `.cursor/commands/adlc-*.md` |
| Kickoff prompt | `.cursor/prompts/adlc-kickoff.md` |
| Strategy / validation prompt | `.cursor/prompts/adlc-product-strategy.md` |

## Default workflow (Cursor)

1. *(Recommended once)* Run `/adlc-product-strategy` (or `@.cursor/prompts/adlc-product-strategy.md`) for market validation and Cup readiness; review `specs/002-product-strategy/report.md`.
2. Open `.cursor/prompts/adlc-kickoff.md` and run it (or `@`-mention it).
3. Fill gaps in constitution + product vision when the agent asks (fold accepted strategy decisions in).
4. Use slash commands in order: `/adlc-ticket` → `/adlc-spec` → `/adlc-approve-spec` → `/adlc-decompose` → build → `/adlc-verify-build` → `/adlc-prosecute`.

## CLI

```bash
npm i -g @adlc/cli
adlc --help
adlc preflight
adlc spec-lint .adlc/specs/<spec>.md --prompt-only
```

Inside Cursor, prefer `--prompt-only` on LLM-backed gates — the agent answers the printed prompt (no extra API key).
