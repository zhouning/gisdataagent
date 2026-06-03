# Standards Platform Wave 6-eval Design

- **Status**: Implemented first slice (2026-06-03)
- **Date**: 2026-06-01
- **Scope**: v25.3 first slice, derivation quality evaluation baseline
- **Related roadmap**: `docs/roadmap.md` v25.3-eval

## Goal

Build a small, testable evaluation layer for Standards Platform derivation quality. The first slice scores human gold items against predicted derivation items, reports precision / recall / F1 overall and per strategy, and produces machine-readable plus Markdown reports.

The acceptance target follows the roadmap: overall precision >= 0.85 and overall recall >= 0.75.

## Non-goals

- No UI.
- No production derivation behavior changes.
- No LLM-as-judge in this slice.
- No automatic DB gold-set creation.
- No EA / reverse-XMI export.

## Design

The evaluator works on a stable item schema shared by all six derivation strategies:

```json
{
  "strategy": "to_semantic_hint",
  "source_key": "data_element:cq_dltb.dlbm",
  "target_kind": "semantic_hint",
  "target_key": "cq_dltb.dlbm:other",
  "match": {
    "hint_kind": "other"
  },
  "payload": {
    "hint_text_zh": "..."
  }
}
```

`strategy`, `source_key`, `target_kind`, `target_key`, and canonical JSON of `match` form the exact match identity. `payload` is retained as evidence but does not affect identity.

This keeps scoring deterministic and strategy-neutral:

- `to_semantic_hint`: match column scope and hint kind.
- `to_value_semantics`: match column scope, hint kind, and value-domain essence.
- `to_synonym`: match semantic source table and synonym token.
- `to_qc_rule`: match rule name/type and essential config.
- `to_defect_code`: match defect code and binding kind.
- `to_data_model`: match model snapshot layer/stats/DDL capability markers.

## Components

- `data_agent/standards_platform/evaluation/schema.py`
  - Dataclasses for eval items, eval sets, metric summaries, and reports.
  - JSON loading and validation.
- `data_agent/standards_platform/evaluation/extractor.py`
  - Read active `std_derived_link` rows for one `std_document_version`.
  - Convert supported downstream target rows into the common eval item schema.
  - Supported target tables in this slice: `agent_semantic_hints`, `agent_semantic_sources`, `agent_quality_rules`, `agent_defect_code_bindings`, and `std_data_model_snapshot`.
- `data_agent/standards_platform/evaluation/scorer.py`
  - Exact set scoring by canonical item identity.
  - Overall and per-strategy precision / recall / F1.
  - Threshold pass/fail calculation.
- `data_agent/standards_platform/evaluation/report.py`
  - Markdown rendering for CI logs and human review.
- `data_agent/standards_platform/evaluation/cli.py`
  - Offline command: load a human gold JSON file, extract predictions for one version, score, and write JSON plus Markdown reports.
  - Exit code `0` when thresholds pass, `1` when metrics miss thresholds.

## Error Handling

- Missing required fields raise `ValueError`.
- Duplicate item identities in a gold or prediction set raise `ValueError`; duplicates hide false positives and make metrics misleading.
- Extractor skips stale/superseded links by default and only reads active predictions.
- Extractor emits a payload note for unsupported target tables rather than failing the entire version.
- Empty gold plus empty predictions returns precision=1.0, recall=1.0, F1=1.0.
- Empty gold with predictions returns precision=0.0, recall=1.0, F1=0.0.

## Testing

Use pure unit tests first:

- schema validation and duplicate detection
- exact-match scoring
- per-strategy aggregation
- threshold pass/fail
- Markdown report content
- CLI JSON/Markdown output and exit codes

Follow-up slices can add DB extractors and real 50-clause gold sets after the scoring contract is stable.
