**Close the gaps with a focused submission-readiness sprint. Keep the current architecture and concentrate on correctness, credible evidence, and deployment.**

Run deployment preparation and submission writing alongside the code fixes so billing or IAM problems surface early.

**1. Fix the trust defects first.**

| Change | Acceptance check |
|---|---|
| Render financial claims from validated engine fields | An explanation with swapped cost/savings or an invented percentage is rejected or replaced |
| Aggregate duplicate SKUs before applying promotion limits | Six milk units entered once or as `3 + 3` produce the same total |
| Preserve fractional receipt quantities | `0.375 kg` remains `0.375` through extraction, history, and planning |
| Give the agent the receipt-updated household history | UI and agent return identical pantry dates after an upload |
| Enforce bounded, in-memory receipt handling | An accepted upload creates no temporary file; oversized uploads are rejected |
| Make model calls asynchronous with a timeout | Receipt extraction does not block unrelated requests |
| Handle unavailable single-store baselines | A valid two-store basket still succeeds when neither store carries everything |

Add focused regression tests for these cases, then run the existing suite. Broader card support can follow later if today’s demo clearly limits eligibility to its configured credit products.

**2. Prove one trustworthy shopping scenario.**

Choose a small basket and one offer whose **complete official terms** you can obtain: card eligibility, exclusions, minimum, cap, validity, and stacking rules.

Manually calculate a qualifying basket and a refused basket, then compare both with the engine.

**Done when:** another person can reproduce the totals from the recorded prices and terms. If complete terms are unavailable, keep the scenario explicitly simulated.

Also correct the evidence labels:

- Disclose **26 real bills plus 17 fictional bills**.
- Demonstrate the pantry using real history alone.
- Replace “before items run out” with “before the estimated next purchase date.”
- Label LKR 1,331 as **simulated savings** until verified inputs support it.
- Present savings against the **best single-store plan** prominently; retain the shelf-price comparison separately.

**3. Demonstrate measurable Gemini value.**

Use the actual configured Gemini model on the existing redacted receipt. Compare its output with the human transcription, including fractional quantities and unsupported items.

Record the model, date, processing time, correct SKU/quantity matches, omissions, and false additions. Capture an actual agent tool trace comparing another day or store limit.

**Done when:** the deployed demonstration visibly shows:

> Receipt → updated pantry → changed shopping plan → tool-backed explanation.

One successful receipt proves integration. A small collection of receipts begins to establish accuracy; report the sample size honestly.

**4. Deploy and test the public judge path.**

Prepare Cloud Run immediately, then deploy the corrected build using the documented service-account configuration.

**Done when:** someone outside the development environment can complete the flow without assistance, including live extraction, explanation, visible failure handling, and mock approval. Record cold and warm response times and put the URL in the README.

**5. Strengthen the business evidence and submission.**

Conduct one short household walkthrough: ask how they would shop before showing the recommendation, then observe whether the plan changes their decision and whether the extra trip feels worthwhile.

Describe this as a household walkthrough. Actual savings require a subsequent purchase.

Build the deck and video around **auditable grocery decisions**, showing one changed constraint and one refused offer. Complete the deployed link, public repository, deck, and video under three minutes required by the [official FAQ](https://aibuildercup.com/Faqs.html).

After submission, prioritize retailer data access, multiple-household pilots, purchase-versus-plan reconciliation, and willingness to pay.

For implementation, put the changed behaviors and checks above into a narrow ADLC spec amendment. Your repository requires **P1 human approval before building and P6 behavioral acceptance afterward**.