# GWM-Bench Foundation V6.0 Draft

Current status: `DEFINED_CANDIDATE_ADMISSION_OPEN_NOT_ACTIVATED`.

V6 is not a larger retrospective rerun of V5. It is a frozen-model external action benchmark. One model package must predict at least two genuinely new hidden actions before any hidden target is opened.

## Activation minimum

- the four frozen V5 events remain development evidence;
- at least two additional development events must be admitted;
- at least two hidden test events must be admitted;
- every event needs 52 pre-action weeks, 12 post-action weeks and at least 50 stable spatial units;
- at least one hidden action must have heterogeneous spatial exposure;
- all hidden predictions must be committed before any hidden target access;
- the same frozen model package must be used across the hidden set.

The current registry contains two screened leads and zero admitted events:

- `nyc_2012_metered_fare_bundle`: hidden-test lead; outcome rows remain unopened, but independent custody, full 64-week coverage, stable spatial reconstruction and implementation evidence are missing;
- `chicago_2026_metered_fare_bundle`: development-only lead; the 12-week post window does not complete until 2026-09-22 and source/action checks remain open.

Therefore V6 data materialization, model training and hidden outcome download are currently prohibited.

## Validate the definition

```bash
.venv/bin/python benchmarks/gwm_bench_foundation_v6_0_draft/validate_v6_definition.py
```

Expected current result:

`PASS_V6_DEFINITION_VALIDATED_NOT_ACTIVATED`

## Files

- `suite_protocol.json`: task, data minimum, Runtime-R5 and frozen result gate;
- `candidate_admission_contract.json`: non-negotiable event admission checks;
- `candidate_registry.json`: screened candidates, blockers and admission state;
- `definition_validation_report.json`: machine validation and current activation result;
- `validate_v6_definition.py`: offline validator; it performs no network access or data download.

Chinese definition:
`docs/research/GWM_BENCHMARK_V6_0_DEFINITION_AND_ACTIVATION_GATE_2026-07-24.md`.
