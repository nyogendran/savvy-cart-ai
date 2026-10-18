**Yes—the business problem and architecture are credible choices for AI Builder Cup 2026.** You have a promising prototype with a clear retail use case. I would currently rate its engineering foundation more strongly than its demonstrated business impact or differentiation.

I reviewed the application code, fixtures, tests, specifications, ADLC records, and deployment documentation, and checked the official competition requirements. **All 63 tests pass**, both documentation checks pass, and the local HTTP flow completes through the mock approval. Live Gemini behavior and visual/mobile usability remain unverified. No source code was changed.

**The competition fit is strong, but deployment is now essential.**

The official rubric weights technical merit and GenAI at 40%, impact at 25%, innovation at 25%, and UX at 10%. Your product fits Retail & Commerce through personalized shopping and purchase planning. A working Google Cloud deployment is mandatory; your confirmed deployment gap therefore prevents the current build from being submission-ready. [Official requirements](https://aibuildercup.com/themes.html)

| Criterion | My assessment |
|---|---|
| Technical merit — 40% | Strong foundation: exact optimization, real ADK tools, receipt extraction, explainable calculations. Live AI evidence and correctness fixes remain. |
| Problem and impact — 25% | Specific, understandable problem. Evidence comes predominantly from one household; actual savings and adoption are unproven. |
| Innovation — 25% | Moderate today. Auditable offer conditions and trip-aware basket allocation are the strongest differentiators. |
| UX — 10% | Coherent guest wizard with useful defaults and explicit mock boundaries. Browser and mobile testing still needed. |

**The business problem is worth keeping.**

“Which supermarket is cheapest?” is fairly generic. Your stronger question is:

> Given what this household needs, the cards it owns, offer conditions, and the cost of another trip, what shopping plan actually costs least?

That connects several decisions shoppers otherwise make separately. The receipt history gives the problem credibility, and showing an offer that refuses a basket is a compelling demonstration of value.

However, **the LKR 1,331 showcase saving is a simulated result, not measured household savings**. Competitor prices, store promotions, and decisive bank conditions are fictional or assumed. Applying the full “up to 25%” headline cannot establish an obtainable discount without complete terms. The disclosures help, but the headline result needs equally prominent qualification. [README](C:/yogi/personal/ai-builder-cup/savvy-cart-ai/README.md:9)

Differentiation also needs care: [Ithuru already advertises](https://ithuru.lk/) store, day, and bank-card comparisons. Its marketing does not establish that those capabilities work, but it means the broad concept is already familiar. Your defensible distinction should be **transparent calculations, complete offer conditions, receipt-derived needs, and travel costs**.

Commercially, the largest unresolved questions are access to dependable retailer data, maintaining offer rules, and who pays. An embedded planner for an issuer or retailer is a plausible buyer hypothesis; the repository does not yet validate it.

**The hybrid architecture is sensible.**

Gemini handles messy receipt text and explanations; deterministic code handles money and eligibility. OR-Tools is justified by store assignment, minimum spends, caps, and trip costs. The ADK implementation genuinely exposes tools and records their results. [Agent implementation](C:/yogi/personal/ai-builder-cup/savvy-cart-ai/src/savvycart/agent.py:114)

Cloud Run is appropriate for this prototype. More services or more agents would contribute less than reliable data and a convincing live demonstration.

The GenAI scoring risk is that the sample experience works without Gemini. That is useful resilience, but judges should see **a real receipt extraction changing the pantry and plan**, followed by an actual tool-assisted comparison.

**Several code findings weaken the current trust claims.**

| Priority | Finding and consequence |
|---|---|
| High | **The explanation guardrail validates digit presence, not meaning.** “You pay 1331 and save 4609; get 23% off” passes when the actual cost is 4609, saving is 1331, and the date contains 23. Use validated field references and deterministic rendering for factual claims. [explain.py](C:/yogi/personal/ai-builder-cup/savvy-cart-ai/src/savvycart/explain.py:53) |
| High | **Duplicate SKU rows bypass promotion quantity limits.** Six milk units cost LKR 3,204 in one row but LKR 3,000 as two rows of three. This is reachable through the agent tool. Aggregate quantities before applying limits. [planner.py](C:/yogi/personal/ai-builder-cup/savvy-cart-ai/src/savvycart/planner.py:93) |
| High | **Uploads contradict “never written to disk.”** Multipart parsing spooled a 2 MB receipt to a temporary file before the size check. Persistent retention was not established, but temporary filesystem use was reproduced. [http.py](C:/yogi/personal/ai-builder-cup/savvy-cart-ai/src/savvycart/http.py:1146) |
| Medium | **Weighted quantities are rounded incorrectly.** Extraction converts 0.375 kg into 1, although the planner supports fractional quantities. Preserve decimal quantities throughout. [gemini.py](C:/yogi/personal/ai-builder-cup/savvy-cart-ai/src/savvycart/gemini.py:51) |
| Medium | **The agent can use stale household history.** Newly uploaded purchases update the UI, while `get_pantry` reads static repository history. The agent can therefore contradict the shopper’s latest receipt. [agent.py](C:/yogi/personal/ai-builder-cup/savvy-cart-ai/src/savvycart/agent.py:43) |
| Medium | **A valid multi-store plan can fail during baseline calculation** when no single store carries the complete basket. An unavailable baseline should not discard the valid plan. [planner.py](C:/yogi/personal/ai-builder-cup/savvy-cart-ai/src/savvycart/planner.py:204) |

Additional robustness gaps include synchronous receipt inference blocking the async request handler and card eligibility matching issuers without fully matching product/network restrictions.

There are also two evidence corrections: pantry calculations combine **26 real bills with 17 fictional bills**, which deserves clearer disclosure; and median purchase gaps estimate a next purchase date, rather than establish when food runs out.

**For today’s deadline, I would prioritize these actions:**

1. **Fix the trust issues above**, especially incorrect savings explanations and promotion limits.
2. **Deploy to Cloud Run and verify live extraction and agent tools externally.** Record the model configuration and observed latency.
3. **Demonstrate one completely verified offer**, including exclusions, minimum, cap, eligibility, and stacking rules. Label remaining savings as simulated.
4. **Record a focused demo:** receipt → changed basket → optimized plan → changed trip cost or wallet → refused offer → approval preview.
5. **Complete the submission pack.** The official FAQ requires a deployed link, public GitHub repository, deck, and video **under three minutes**. The repository’s submission ticket is currently parked. [Submission requirements](https://aibuildercup.com/Faqs.html)

I would keep this business problem and architecture. The next investment should be **verified inputs, corrected trust guarantees, live AI evidence, and a clear demonstration of household value**.