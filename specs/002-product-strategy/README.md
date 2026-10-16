# Product strategy & market validation

Pre-build evidence pack for SavvyCart AI — optimized for **AI Builder Cup top-5 / Demo Day shortlist** under the official **40 / 25 / 25 / 10** rubric, grounded in [themes](https://aibuildercup.com/themes.html) + [Ask-the-Expert](https://www.youtube.com/watch?v=_75UeGNj1GY).

| Artifact | Path |
| --- | --- |
| Master prompt (run this) | `.cursor/prompts/adlc-product-strategy.md` |
| Slash command | `/adlc-product-strategy` |
| Strategy report (output) | `specs/002-product-strategy/report.md` |
| Cup canon snapshot | `specs/000-hackathon-context/context.md` |

**Report status (17 Oct 2026):** narrow slice **accepted** in kickoff Round 1. Folded into `specs/001-product-vision/spec.md` and `specs/000-hackathon-context/context.md`. The report is still not an executable spec; the lintable copy will be `.adlc/specs/SC-001-product-vision.md`.

## When to run

**Before** freezing product vision (`/adlc-kickoff` / P0–P1), or whenever the team needs a candid go / narrow / pivot / abandon check aimed at shortlist odds — not feature ambition.

## After the report

1. Human reviews `report.md`.
2. Accepted decisions → fold into `specs/001-product-vision/spec.md` and `specs/000-hackathon-context/context.md`.
3. Continue ADLC: `/adlc-kickoff` → `/adlc-ticket` → `/adlc-spec` → …

Do not treat this report as an approved executable spec. Gate tools still need a lintable file under `.adlc/specs/` after interrogation.
