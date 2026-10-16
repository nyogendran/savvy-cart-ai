---
description: >-
  Pre-build product strategy optimized for AI Builder Cup top-5 / Demo Day
  shortlist. Grounded in official themes/judging + Ask-the-Expert video.
  Writes specs/002-product-strategy/report.md — no application code.
---

# MASTER PROMPT: TOP-5 COMPETITION STRATEGY — SAVVYCART AI (AI Builder Cup 2026)

Use this prompt in a **dedicated chat** before freezing product vision (`/adlc-kickoff` / P0–P1). Do **not** write application source code. Persist the final report under `specs/002-product-strategy/report.md` and fold durable decisions into `specs/001-product-vision/spec.md` and `specs/000-hackathon-context/context.md` only after the human accepts them.

## Mission (non-negotiable)

Your job is **not** to produce an attractive business plan or agree with the founder.

Your job is to design the **strongest achievable submission** that maximizes the probability of:

1. Passing mandatory eligibility / submission hygiene (no DQ).
2. Scoring in the **top shortlist** for Singapore Demo Day (treat “first 5 places” as the internal target — exact shortlist size is organizer-controlled).
3. Surviving skeptical judges on **Technical Merit & Gen AI (40%)** without collapsing on problem fit, originality, or UX.

Be candid. Challenge weak assumptions. Prefer a narrower, demoable, Google-Cloud-native prototype over an ambitious multi-partner fantasy.

Distinguish clearly: **verified fact** | **reasonable inference** | **unvalidated assumption** | **recommendation**.

---

## 0. Verified competition canon (read first; cite in the report)

Cross-check these sources before inventing rules. If a source conflicts, prefer the official site / FAQ, then label the conflict.

| Source | URL |
| --- | --- |
| Official site | https://aibuildercup.com/ |
| Themes + judging + build rules | https://aibuildercup.com/themes.html |
| FAQs | https://aibuildercup.com/Faqs.html |
| Ask-the-Expert session (mandatory review) | https://www.youtube.com/watch?v=_75UeGNj1GY |
| Local snapshot | `specs/000-hackathon-context/context.md` |

### 0.1 Official premise (site)

> Start with a problem you understand, build a solution on Google Cloud, and show that something built for a **local need can scale to a global one**.

### 0.2 Themes (choose exactly one)

From https://aibuildercup.com/themes.html — one team, one theme:

1. **BFSI:** Intelligent Risk, Fraud & Financial Experiences  
2. **Retail & Commerce:** Intelligent Customer and Business Experiences *(default hypothesis for SavvyCart — validate)*  
3. Manufacturing  
4. Media, Content & Digital Experiences  
5. Future of Work & Enterprise Productivity  
6. Sustainability & Social Impact  

Retail theme language explicitly includes: discovery, personalization, conversational shopping, demand planning, inventory, customer insights, fraud. Map SavvyCart features to those words in the deck.

### 0.3 Hard technical requirements (site + Ask-the-Expert)

Verified / strongly stated:

- Prototype must use **Google AI models (Gemini or Gemma)** and/or **agentic platforms** (Agent Platform / Antigravity / AI Studio). Custom ML alone is **not** enough — Gemini must be used for reasoning or equivalent visible GenAI role ([themes](https://aibuildercup.com/themes.html); Abrami in video).
- Deploy the judge-facing app on **Cloud Run or Firebase**. Deployment elsewhere alone fails the game rules (Abrami: “Cloud Run or Firebase… that’s the game rules”).
- Primary cloud stack must be Google Cloud; other-cloud-primary solutions are ineligible ([FAQ](https://aibuildercup.com/Faqs.html)).
- Working end-to-end prototype — not slides-only ([FAQ](https://aibuildercup.com/Faqs.html)).
- **Fresh work during the hackathon timeline** preferred/required by FAQ; if adapting commercial IP, still need a submission-safe repo with enough evidence for technical soundness (Abrami nuance — label uncertainty vs FAQ “fresh only”).
- English for all submission materials ([themes](https://aibuildercup.com/themes.html)).
- **Secrets in any submission artifact = disqualification** (Abrami: Secret Manager / env vars only; never paste credentials, deploy commands with secrets, etc.).

### 0.4 Mandatory submission pack (disqualify if incomplete)

From dashboard walkthrough in the video + FAQ/themes:

| Artifact | Requirement | Notes / conflicts to resolve |
| --- | --- | --- |
| Pitch deck | PDF proposal: problem, impact, theme alignment, feasibility, scalability | Themes page “Clear Proposal” |
| Demo video | Show real product behavior | **Conflict:** site/FAQ say **under 3 minutes**; Ask-the-Expert host said **~3–4 minutes**. Default to **≤3:00** unless portal text overrides — state which you followed |
| Deployed URL | Live Cloud Run **or** Firebase URL judges can open | Must remain functional through evaluation; downscaling to zero on Cloud Run is OK (Abrami) |
| Public GitHub | Accessible repo proving GenAI + GCP usage | Prefer public; if private, grant judge access — Abrami prefers open demo without login friction unless auth is the product |
| Description | How you use Gemini / Firebase / Firestore / Cloud Run / Agent Platform pieces | Explicit GCP AI stack narrative |

**Critical (video):** If the app, APIs, or integrations are down during evaluation → **cannot be scored / effectively DQ**. Keep the endpoint alive through **19 Oct – 6 Nov 2026** evaluation window ([site timeline](https://aibuildercup.com/)).

### 0.5 Official judging weights (same across all themes)

From https://aibuildercup.com/themes.html and FAQ:

| Criterion | Weight | Sub-bullets judges use |
| --- | --- | --- |
| **Technical Merit & Gen AI Implementation** | **40%** | Meaningful GenAI (solves the problem, not bolted on); functional technical implementation; scalability & sustainability beyond prototype |
| **Problem Alignment & Impact** | **25%** | Aligns to chosen theme/problem; clear value for users / stakeholders |
| **Innovation & Creativity** | **25%** | Differentiation vs existing solutions; creative GenAI use beyond superficial chatbot |
| **User Experience & Solution Design** | **10%** | Usability/accessibility; cohesive integration of GenAI into the experience |

**Optimization implication:** Every architecture and MVP decision must justify how it earns points in the **40%** bucket without starving the 25%+25%. A beautiful UX with shallow GenAI loses. A clever agent with unclear problem fit loses.

### 0.6 Ask-the-Expert win / lose signals (Abrami Sukumaran, Google Cloud Staff DA)

Treat these as **high-signal judge heuristics** (not a substitute for the rubric):

**Earns points / edge**

- Visible **Agent Platform / ADK 2.0** competence (not mandatory exclusive scorer, but recommended to demonstrate technical depth).
- Clear **grounding + guardrails** (own data via tools; Google Search grounding optional if data is solid).
- Document **latency / tool-call strategy** if you solved multi-tool agent latency — one-liners in video/deck help.
- Video + docs include: **sample user questions**, expected behavior, login/test notes, **what the app can and cannot do**.
- Synthetic / simulated data is **acceptable if labeled** (Abrami explicit).
- Hybrid custom CV/ML + Gemini reasoning OK **if Gemini is still used**.
- Prefer judge path with **minimal login friction**; supply test credentials if auth required.
- Redeploy same endpoint OK; scale Cloud Run to zero when idle.
- Open demo video with **live product** (Abrami personal preference): ask → cut to architecture journey → return to answer/impact.

**Loses points / DQ risk**

- Missing any mandatory artifact; dead deploy during evaluation.
- Secrets / credentials in repo or deck.
- Video: **low volume, unclear audio, hard to understand flow** (called out as common failure mode, including prior events).
- Strong tech that **doesn’t answer the chosen problem / theme language**.
- Idea great but prototype **too thin / too basic** — “could have gone the extra mile.”
- Feasibility skepticism: judges conclude it **won’t work in the real world**.
- Custom model **without** Gemini.
- Pure chatbot on a spreadsheet with no meaningful agent/tool/multimodal depth (fails Innovation + Technical Merit).
- Over-gated demos that hide the product behind unnecessary auth.

### 0.7 Timeline (verify; note conflicts)

| Milestone | Official site | Video note |
| --- | --- | --- |
| Prototype deadline | **18 Oct 2026** | Host: no extension — next stage starts after |
| Evaluation | 19 Oct – 6 Nov 2026 | App may be tested any day in window |
| Finalists | 7 Nov 2026 | Visa prep immediately if shortlisted |
| Demo Day Singapore | 4 Dec 2026 | Only **2** travelers; flights/accommodation/meals sponsored; visa own cost |
| Team formation | Site: to 14 Oct; registration to 11 Oct | Host said team formation reopened to **16 Oct** — **verify dashboard**; cannot submit without a team |

Eligibility: working professionals / entrepreneurs / startups only; **21+**; **JAPAC-based**; no students (team-wide DQ if any student). Prize pool USD 30,000.

### 0.8 Video access duty

Before evaluating the idea:

1. Review https://www.youtube.com/watch?v=_75UeGNj1GY (full session, including ~36:39+ Q&A if using timestamped links).
2. Prefer transcript + on-screen dashboard/submission guidance.
3. If video inaccessible, say so explicitly; use site/FAQ only; mark conclusions provisional.
4. Do **not** invent video content.

---

## 1. Your Role

Act as a multidisciplinary expert team:

- Senior AI product strategist (hackathon / innovation competitions).
- AI agent / multi-agent architect with hands-on **Google Cloud Agent Platform, ADK, Vertex/Gemini, Cloud Run**.
- Sri Lankan retail, supermarket, e-commerce, and consumer-finance researcher.
- Competitive intelligence analyst (retail tech, price comparison, loyalty, personalized commerce).
- Fintech / payments specialist (banking APIs, card-linked offers, privacy, authorization).
- Startup PM under severe time constraints (deadline **18 Oct 2026**).
- UX researcher (South Asian consumer shopping behavior).
- **Hostile Cup judge** optimizing for the **40/25/25/10** rubric and Abrami’s failure modes.

---

## 2. Top-5 Winning System (apply to every recommendation)

### 2.1 Score the concept the way judges will

For **current concept** and **revised concept**, produce a predicted scorecard (0–100 composite = weighted sum):

| Criterion | Weight | Score 0–100 | Weighted | Evidence you would show judges |
| --- | --- | --- | --- | --- |
| Technical Merit & Gen AI | 0.40 | | | |
| Problem Alignment & Impact | 0.25 | | | |
| Innovation & Creativity | 0.25 | | | |
| UX & Solution Design | 0.10 | | | |
| **Composite** | 1.00 | | | |

Do **not** inflate scores. Explain each score with explicit criteria. Separate idea quality from implementation-plan quality.

Also give:

- Overall verdict: Strong finalist candidate / Promising if narrowed / Weak differentiation / Not recommended.
- Three biggest advantages **for this rubric**.
- Five most serious DQ or point-loss risks.
- Single most compelling reason a judge **selects** SavvyCart for Demo Day.
- Single most compelling reason a judge **rejects** it.
- Clear **build / narrow / pivot / abandon** recommendation aimed at top-5 odds — not vanity scope.

### 2.2 Point-budget architecture rule

Allocate build effort roughly proportional to scoring weight:

- **~40% effort → GenAI depth that is load-bearing:** multimodal receipt understanding, promotion-condition extraction, explanation of savings under uncertainty, agent tool use with grounding — not a chat UI glued to static prices.
- **~25% → Theme-locked problem story:** Sri Lanka local pain → JAPAC / global scale narrative; map explicitly to **Retail & Commerce** (or justify BFSI if card-offer optimization is the primary claim).
- **~25% → Differentiation:** basket-level optimization + card+retailer offer logic + explainability that competitors don’t show in one flow.
- **~10% → UX polish that makes the GenAI path feel inevitable** — clear approval checkpoint, readable savings, mobile-friendly demo path.

Anything that does not move one of these four buckets is **post-competition**.

### 2.3 “Not a spreadsheet chatbot” test

The submission fails Innovation + Technical Merit if a judge can fairly describe it as:

> A chatbot that reads a price CSV and restates discounts.

The MVP must visibly show at least:

1. **Multimodal or document AI** on a real/receipt-like artifact (Gemini).  
2. **Tool-using agent behavior** (profile / prices / promotions / optimize / explain) with deterministic optimization where math matters.  
3. **Auditable net savings** (baseline vs optimized; uncertainty labeled).  
4. **Human purchase approval** before any order action.  
5. **Cloud Run or Firebase** live URL + Agent Platform/ADK or equivalent Google agent stack evidence in repo.

### 2.4 Non-goals for Cup submission

Deliberately avoid (unless already done and free):

- Live bank/supermarket order APIs without verified access.
- Scraping restricted sites.
- Storing PAN/CVV or real card numbers.
- Multi-category retail (fashion, electronics) in MVP.
- Perfect Sinhala/Tamil UX if it burns the English demo (English materials mandatory; local language can be stretch).
- Heavy BigQuery/AlloyDB unless latency story needs it — prefer smallest stack (Firestore + Cloud Run + Gemini) unless evidence says otherwise.

---

## 3. Original Product Concept (to stress-test)

Working name: Savi AI Shopping / **SavvyCart AI**.

Multimodal, agentic AI shopping assistant initially for **Sri Lanka**, combining:

- Personalized shopping history / patterns.
- Current supermarket prices and availability.
- Bank-card promotions, cashback, rewards.
- Retailer promotions, coupons, loyalty.
- Household needs, budgets, recurring purchases.
- Substitutions and cross-retailer comparison.
- User-approved ordering and delivery.

AI recommends and explains; **user approves** before order/payment.

Retailers to investigate (do **not** assume public APIs): Keells, Cargills Food City, SPAR Sri Lanka, Glomark, others with evidence.

Banks to investigate: Commercial Bank, NTB, HSBC Sri Lanka, HNB, Sampath, People’s Bank, Bank of Ceylon, Seylan, others with evidence.

Delivery: Uber Eats, PickMe — only if integration path verified; otherwise simulate and label.

Data via authorized integrations, user-uploaded receipts, consent-based sources. Prefer curated/simulated labeled datasets for prototype.

Respect repo constitution: never invent prices as “live”; surface uncertainty; no secrets in git; minimize PII.

---

## 4. Core Hypothesis

> Consumers make better, more economical shopping decisions when an AI assistant combines actual needs, current prices, card-linked benefits, retailer promotions, and delivery costs into one personalized, explainable basket recommendation.

Validate importance and underserved nature. Pick **one primary value prop** among: lower grocery spend, best full-basket retailer, max card+promo value, planning simplicity, waste reduction, time saved, controlled automation.

For Cup impact scoring, also write the **local → global** scaling sentence judges expect.

---

## 5–15. Research & design deliverables

Complete all of the following in the report. Keep every recommendation tied back to §2 Top-5 Winning System and §0 canon.

### 5. Executive Verdict

Include §2.1 scorecard + build/narrow/pivot/abandon for **top-5 odds**.

### 6. Market Research & Gap Analysis (Sri Lanka)

Cover existing solutions, competitors (named with evidence), gap table:

| Potential market gap | Evidence | Existing alternatives | Customer pain | Opportunity for SavvyCart | Confidence |

Identify ≥3 evidence-backed gaps **or** state that evidence does not support three. Rank by customer importance, differentiation, feasibility, time-to-prototype. No fabricated stats.

### 7. Customer Segments & Validation Plan

Evaluate segments; pick primary + secondary; ≥10 non-leading interview questions; pilot design; measurable evidence that confirms/disproves hypothesis (interest ≠ willingness to pay).

### 8. Differentiation & Positioning

Score positioning options A–E (grocery savings assistant; basket optimizer; card+promo agent; autonomous household agent; multimodal purchasing assistant) on novelty, value, explainability, differentiation, feasibility, **≤3 min demo fit**, growth.

Recommend one. Produce one-sentence description, 30s pitch, problem, solution, value prop, 3 differences, why AI is necessary.

Name evaluation: SavvyCart AI, Savi SmartCart, CartWise — mark trademark availability unknown if unverified.

**Theme lock:** Explicitly choose Retail & Commerce vs BFSI and justify with rubric language.

### 9. Winning MVP (Cup-shaped)

Design the **smallest end-to-end** journey that proves the hypothesis **and** maximizes rubric points:

Budget/needs → receipt/history → extraction → cards/preferences → price+promo dataset (labeled source) → basket compare → net savings + explanation → user edit/reject → approval → order preview (live order only if authorized integration exists).

Classify features: Essential for Cup MVP | Time-permitting | Post-Cup | Not now.

Feature matrix: customer value × complexity × risk × **rubric impact (esp. 40% GenAI)**.

Grocery-only vs multi-category: prefer grocery-only unless evidence says otherwise.

### 10. Savings Logic

Define full-basket optimization (not single-SKU cherry picking). Formulas for baseline, optimized, immediate savings, effective cost after benefits, %, switching/delivery costs, net benefit. Separate cash vs deferred cashback/points; prevent double-counting. Worked **hypothetical LKR** example clearly labeled fictional. Handling: missing prices, conflicts, stale data, uncertain eligibility. Method: ILP vs rules — pick MVP-appropriate.

### 11. Multimodal Multi-Agent Architecture (Google-native)

Design for **visible GenAI merit**:

Candidate agents: Profile, Receipt Understanding (multimodal/OCR), Price Intelligence, Promotion Intelligence, Basket Optimization (**prefer deterministic math**), Explanation, Purchasing (approval-gated).

Decide: 7 agents vs smaller orchestrator + tools. Define agent vs optimizer vs API vs chatbot. Prefer ADK / Agent Platform patterns judges recognize; document grounding and guardrails.

### 12. Google Cloud Blueprint (smallest reliable)

Verify current GCP capabilities before prescribing. Prefer: Gemini (multimodal) + Cloud Run and/or Firebase + Firestore + Cloud Storage + Secret Manager + IAM + logging. Add Agent Platform/ADK, Document AI, Pub/Sub, etc. only if they raise the 40% score more than they burn schedule.

Deliver: Mermaid architecture, data/agent flow, API contracts, schema, auth (judge-friendly path), deploy steps, indicative prototype cost, security, **test plan without partner APIs**, **evaluation-window keep-alive plan** (Cloud Run scale-to-zero OK).

### 13. Integration Feasibility

Table:

| Provider | Required capability | Verified path | Access conditions | Prototype fallback | Risk |

No assumed public APIs. No scraping bypass. Provider-independent adapters with labeled mocks.

### 14. Security, Privacy, Trust

Sri Lankan PDPA / consumer / e-transactions / payments research with citations. Consent, minimization, receipt handling, no raw PAN/CVV, approval before purchase, anti-prompt-injection on receipts, no false savings claims, sponsored-offer transparency. Human approval mandatory.

**Cup hygiene:** zero secrets in GitHub/deck/video descriptions.

### 15. Business Model

Evaluate models; recommend one initial; conservative/base/optimistic with labeled assumptions. Keep Cup narrative focused on impact + scalability, not revenue theater.

---

## 16. Competition Scorecard & Hostile Judge Panel

Build the weighted scorecard (§2.1) with **verified official weights** — do not invent alternate percentages.

Assess Abrami failure modes explicitly:

| Failure mode | Present? | Mitigation in MVP/deck/video |
| --- | --- | --- |
| Dead deploy during evaluation | | |
| Secrets leak | | |
| Unclear / quiet video | | |
| Wrong theme / unanswered problem | | |
| Too thin vs claimed ambition | | |
| Real-world feasibility doubt | | |
| Spreadsheet chatbot perception | | |
| Login friction hiding the demo | | |

Simulated panel (≥5): AI/engineering, Product/UX, Market, Security/trust, Competition strategy — objections, evidence, fixes.

Name **three memorable demo moments** for judges.

Do not claim predicted scores are actual outcomes.

---

## 17. Demonstration Strategy (submission video ≤3:00 default)

Design a **≤3 minute** submission video (and a separate longer live Demo Day script if shortlisted). Resolve site vs host length conflict in the report.

**Suggested structure (aligned to Abrami):**

| Time | Beat |
| --- | --- |
| 0:00–0:20 | Live product cold open — household budget + receipt upload starts |
| 0:20–0:50 | Problem (Sri Lanka fragmented prices/offers) + theme lock (Retail & Commerce) |
| 0:50–1:40 | Agent journey: extract → prices/promos tools → optimize → explain net savings |
| 1:40–2:20 | Architecture flash: Gemini multimodal, ADK/Agent Platform, Cloud Run/Firebase, Firestore, Secret Manager; grounding/guardrails one-liner |
| 2:20–2:45 | User rejects a substitution → recalc → explicit approve → order preview (mock labeled) |
| 2:45–3:00 | Measurable outcome (hypothetical LKR saved) + local→global scale line + CTA |

Also produce:

- Judge “happy path” sample questions / clicks documented in README.
- What is mock vs live — on-screen labels.
- Audio/clarity checklist (volume, captions optional, no night-whisper recording).
- Screens to build first for both video and live URL.

---

## 18. Time-boxed Roadmap to 18 Oct 2026

Work backward from **submission deadline 18 Oct 2026**. Include buffer for portal upload.

Milestones must include: scope lock, curated dataset, UX, backend, receipt GenAI, deterministic optimizer, frontend, mock adapters, tests, **Cloud Run/Firebase deploy**, **keep-alive config**, video, deck PDF, GitHub hygiene (no secrets), description of GCP AI stack, final buffer.

Each milestone: deliverable, deps, effort, acceptance criteria, risk, fallback.

Team roles: frontend, backend, AI/agent, product/demo, submission owner.

Proposed Cup acceptance criteria (targets, not claimed results), e.g.:

- Deployed Cloud Run/Firebase URL opens without error.
- Receipt extraction hits stated accuracy on labeled test set.
- Savings math unit tests pass (no double-count).
- Agent tools grounded; refusal/guardrail demo path exists.
- End-to-end approval workflow completes in ≤ N seconds on sample path.
- Repo contains architecture + sample judge script; `gitleaks`/secret scan clean.

---

## 19. Future Expansion

Post-Cup only: fashion, electronics, etc. Do not enlarge MVP for optics.

---

## 20. Final Report Structure

Write `specs/002-product-strategy/report.md` in this order:

1. Executive verdict + **predicted rubric scorecard (40/25/25/10)**  
2. Competition & video-alignment assessment (cite site + Ask-the-Expert)  
3. Theme lock (Retail vs BFSI) and local→global narrative  
4. Core problem and hypothesis  
5. Sri Lankan market overview  
6. Competitor landscape  
7. Evidence-based gap analysis  
8. Target customers and validation plan  
9. Recommended name and positioning  
10. Differentiation strategy vs “spreadsheet chatbot”  
11. Recommended MVP scope (Cup-shaped)  
12. Savings calculation and optimization logic  
13. Multimodal AI and agent architecture (ADK/Agent Platform evidence plan)  
14. Google Cloud implementation blueprint + evaluation keep-alive  
15. Integration feasibility  
16. Security, privacy, trust + submission secret hygiene  
17. Business model (brief)  
18. Competition scorecard, DQ checklist, simulated judge feedback  
19. **≤3 min** submission video script + Demo Day extension notes  
20. Time-boxed roadmap to 18 Oct 2026  
21. Mandatory submission pack checklist (deck, video, URL, GitHub, description)  
22. Risks, assumptions, unresolved questions (including site vs video conflicts)  
23. Final go/no-go for **top-5 pursuit**  
24. Sources and research limitations  

---

## 21. Final Decision Framework

Answer directly:

1. Strong differentiated idea, or feature mash without enough GenAI depth for a 40% technical score?  
2. Most defensible Sri Lankan gap?  
3. Smallest prototype that proves that gap **and** looks non-trivial to Cup judges?  
4. What must be Gemini/agent vs deterministic code?  
5. Which integrations are essential vs labeled simulation (explicitly allowed)?  
6. Worst technical, legal, commercial, data-access, and **DQ** risks?  
7. Build first?  
8. Deliberately avoid?  
9. What evidence would most improve top-5 odds in the next 72 hours?  
10. Proceed, narrow, pivot, or abandon — given rules, time, and constraints?

End with the **10 next actions**, prioritized for shortlist probability (not feature greed).

Final recommendation must be candid, Sri Lanka–specific, technically grounded, and optimized for **AI Builder Cup Demo Day shortlisting** — not the most ambitious idea on paper.

---

## Repo handoff (after the report)

1. Write `specs/002-product-strategy/report.md`.  
2. Keep `specs/002-product-strategy/README.md` pointing here.  
3. Propose concrete updates for `specs/000-hackathon-context/context.md` (theme, submission checklist, video lessons) — apply only after human accept.  
4. Stop. Ask whether to fold into vision via `/adlc-kickoff`.  
5. Do **not** create feature tickets or application code from this prompt alone.
