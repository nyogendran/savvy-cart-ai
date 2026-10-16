# ADLC workflow (this repo)

Reference: [Agentic Development Lifecycle](https://www.agenticlifecycle.ai/docs/lifecycle) · [Cursor integration](https://www.agenticlifecycle.ai/docs/integrations/cursor)

```text
P0 Triage ──► P1 Spec (+ human approve) ──► P2 Decompose
    │                                              │
    │                                              ▼
    │                                       P3 Freeze rails
    │                                              │
    │                                              ▼
    │                                       P4 Build + verify
    │                                              │
    │                                              ▼
    │                                       P5 Prosecute
    │                                              │
    │                                              ▼
    └─────────────────────────────────────► P6 Integrate (human)
                                                   │
                                                   ▼
                                            P7 Distill lessons
```

## Day-0 path for Savvy Cart

| Step | Action | Slash command |
| --- | --- | --- |
| 0 | Run kickoff prompt | `@.cursor/prompts/adlc-kickoff.md` |
| 1 | Author ticket | `/adlc-ticket` |
| 2 | Interrogate + lint spec | `/adlc-spec` |
| 3 | **You** approve | `/adlc-approve-spec` |
| 4 | Slice work | `/adlc-decompose` |
| 5 | Implement under rails | (normal agent chat) |
| 6 | Verify | `/adlc-verify-build` |
| 7 | Hostile review | `/adlc-prosecute` |
| 8 | Ship slice / demo | human acceptance |

## Install (once per machine)

```bash
npm i -g @adlc/cli
# Optional: Cursor marketplace plugin from https://github.com/voodootikigod/adlc
```

This repo was already bootstrapped with:

```bash
adlc init --harness cursor
npx @adlc/cursor .
```

## Note on Windows

Upstream ADLC notes incomplete Windows support for some gates. Prefer **WSL** or Git Bash for CLI gates if a tool fails on path handling; Cursor commands still work via `--prompt-only`.
