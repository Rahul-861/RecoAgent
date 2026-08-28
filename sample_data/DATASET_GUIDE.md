# ReconAgent Stress-Test Dataset v2 — Multi-Source Reconciliation

Fresh batch for measuring **current** ReconAgent match-rate / precision / recall / F1,
built to exercise every match tier shown on the Overview dashboard — including the
**LLM adjudication tier**, which showed 0 calls on the last run. This batch adds cases
that a rules engine and a plain fuzzy/embedding threshold genuinely cannot resolve
alone, so if the pipeline is working end-to-end you should see `LLM > 0` this time.

## Files
- `processor.csv` — 201 payment processor events (gross/fee/refund/net).
- `bank.csv` — 236 bank credits/debits (settlements, refunds, unidentified cash, anomalies).
- `erp.csv` — 89 ERP/ledger journals (invoices, settlement batches, partial/overpaid, direct receipts).
- `answer_key.csv` — 323-row ground truth for precision/recall/F1 and exception grading.
- `case_manifest.csv` — judge-facing map of every scenario and which transaction IDs belong to it.
- `finance_reconciliation_demo_v2.xlsx` — same data as Excel sheets for multi-format ingestion testing.

## Category volumes (see `case_manifest.csv` for full detail)
| Category | Count | What it tests |
|---|---|---|
| EXACT_1_TO_1 | 36 | Baseline clean match |
| FEE_AWARE | 16 | Bank net vs ERP gross |
| FUZZY_NAME_DRIFT | 14 | Abbreviation/typo counterparty names |
| TIMING_GAP | 12 | 3-day settlement lag tolerance |
| AMOUNT_MISMATCH | 10 | Should be rejected, not force-matched |
| SEMANTIC_MATCH / UNIDENTIFIED_CASH / MISSING_BANK | 8 each | Description-only inference / true negatives |
| **LLM_PARAPHRASE_PLUS_ROUNDING** | **8** | Fully paraphrased narration **and** amount rounded to nearest 10 — fails both string-match and exact-amount rules at once |
| MANY_TO_ONE | 7 | 4 payments → 1 settlement |
| **LLM_MULTI_CANDIDATE_DISAMBIGUATION** | **7** | Two similar bank rows per vendor; only narrative context picks the true one, decoy must be rejected |
| **LLM_INDIRECT_REFERENCE** | **7** | Bank cites an internal PO/project code, not the invoice id — needs reading counterparty out of free text |
| REFUND_MATCHED | 6 | Refund lifecycle, happy path |
| **LLM_NOISY_OCR_TEXT** | **6** | Garbled/abbreviated statement text (dropped vowels, truncated tokens) |
| **LLM_CROSS_FIELD_ARITHMETIC** | **6** | Bank amount = gross − a narration-only deduction (TDS, chargeback, discount, penalty) not in any fee field |
| DUPLICATE_CANDIDATES | 6 | Two equally plausible bank rows that should **both** stay unresolved |
| ONE_TO_MANY_FULL / ERP_ONLY / DIRECT_BANK_ERP | 5 each | Invoice split across credits / ERP-only / no-processor receipts |
| REFUND_MISSING / PARTIAL_PAYMENT / OVERPAID | 4 each | Lifecycle exceptions |
| **LLM_AMBIGUOUS_MANY_TO_ONE** | **4** | Batch narration lists constituent payment refs out of order inside a sentence, not a clean delimited field |
| CURRENCY_MISMATCH | 4 | Must be rejected despite plausible amount/reference |
| REFUND_DUPLICATE | 3 | Two refund debits for one processor refund |
| MANUAL_ENTRY_* (6 variants) + MANUAL_DUPLICATE_ENTRY | 7 | Data-entry anomalies: amount, date, reference, counterparty, duplicate, missing-reference |

**38 rows total are purpose-built LLM-tier cases** (categories prefixed `LLM_`), spread across
6 distinct mechanisms so a genuine LLM adjudication step — not just a lower fuzzy threshold —
is required to resolve them correctly.

## How to read the results
1. Run the full batch (don't cherry-pick).
2. Compare the **Stage Breakdown** against `case_manifest.csv`: `EXACT_1_TO_1`+`FEE_AWARE` should
   land in Exact/Fee-aware, `FUZZY_NAME_DRIFT`+`LLM_NOISY_OCR_TEXT` should land in Fuzzy or LLM,
   `SEMANTIC_MATCH`+`LLM_PARAPHRASE_PLUS_ROUNDING` should land in Semantic or LLM, and the
   `LLM_*` categories should now actually populate the **LLM** counter instead of showing 0.
3. Grade against `answer_key.csv` (may have multiple rows per `(source, transaction_id)` for
   items with both a valid relationship and a separate lifecycle exception — aggregate them).
4. Categories that should stay **unresolved by design** (grade these as correct exceptions,
   not missed matches): `DUPLICATE_CANDIDATES`, `AMOUNT_MISMATCH`, `MISSING_BANK`,
   `UNIDENTIFIED_CASH`, `CURRENCY_MISMATCH`, `PARTIAL_PAYMENT`, `OVERPAID`, `ERP_ONLY`,
   `REFUND_MISSING`, `REFUND_DUPLICATE`, most `MANUAL_ENTRY_*` rows.
5. Everything else has exactly one correct match in `answer_key.csv` — a match rate below
   ~85% on the non-exception categories, or an LLM count still at 0, points at a real gap
   in the fuzzy/semantic/LLM escalation logic rather than the dataset.
