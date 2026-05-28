# P4 Corpus Build, Datafix, And QC Scripts (2026-05-28)

This folder keeps the minimum reusable scripts needed to reproduce the P4 RFP
corpus build and final package checks. It intentionally excludes one-off debug
probes, meeting notes, generated corpora, source documents, Chroma databases,
and embedding caches.

## Source-Of-Truth Policy

1. Use original RFP documents first.
2. Use verified G2B/Nara data only when a required procurement metadata field or
   project budget is missing from the original document.
3. Treat CSV values as candidates. Before promoting a number, classify its role:
   project budget, estimated price, base amount, qualification threshold,
   payment amount, service fee, date/deadline value, or unrelated reference.

## Expected Inputs

- `data/original_data_list/`: original HWP/PDF RFP files.
- `data/hwpx_664/`: HWPX conversions used to parse HWP originals when available.
- `data/eval/`: evaluation ground-truth files, if available.
- `data/g2b_notice_enrichment_690_strict_budget_reconciled.csv`: reconciled G2B
  enrichment CSV.
- `config/manual_overrides/*.csv`: conservative manual override tables.

Large inputs and generated outputs are not committed to git.

## Main Flow

Run from the repository root. `PROJECT_ROOT` is optional; by default scripts
infer the repo root from this folder location.

```bash
python scripts/corpus/20260528/build_p4_original_corpus_250_690.py
python scripts/corpus/20260528/apply_final_corpus_datafix_20260528.py
python scripts/corpus/20260528/propagate_g2b_notice_deadline_20260528.py
python scripts/corpus/20260528/align_250_690_schema_to_125_20260528.py
python scripts/corpus/20260528/build_slim_corpus_20260528.py
python scripts/corpus/20260528/final_corpus_audit_20260528.py
```

## G2B Enrichment Flow

The G2B scripts live in `scripts/g2b/`. They are separated from corpus scripts
because G2B values are enrichment candidates, not the primary corpus source.

Typical order:

```bash
python scripts/g2b/g2b_keyless_enrichment_from_local_docs.py --project-root . --output data/g2b_notice_enrichment_690_keyless.csv
python scripts/g2b/g2b_notice_detail_fallback.py --project-root . --input data/g2b_notice_enrichment_690_keyless.csv --output data/g2b_notice_enrichment_690_detail.csv
python scripts/g2b/g2b_strict_budget_reconcile.py --project-root . --input data/g2b_notice_enrichment_690_detail.csv --output data/g2b_notice_enrichment_690_strict_budget_reconciled.csv
```

## Final Checks

`final_corpus_audit_20260528.py` checks:

- validation status and manifest hashes
- duplicate `chunk_id` / `source_store_id`
- missing `source_ref.source_store_id`
- G2B notice/deadline propagation mismatches
- internal marker leakage such as `alias 보강`
- slim policy: only `embed_enabled == true`, no `toc` chunks
- suspicious project-duration tail noise

The final shared corpus should pass these checks before handoff.
