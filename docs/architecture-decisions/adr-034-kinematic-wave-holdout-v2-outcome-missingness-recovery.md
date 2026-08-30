# ADR-034: Kinematic-wave holdout v2 outcome missingness recovery

- Status: Accepted
- Date: 2026-07-28
- Scope: v2 outcome acquisition only

## Context

Both v2 predictions were jointly sealed before any USGS request. The frozen
outcome acquisition then verified the protocol, all frozen code hashes, both
prediction hashes, and the joint seal before requesting Center Hill data.

The Center Hill response did not contain a complete approved native-sample set
for the persistence-prior support ending at `2022-11-10T01:00:00Z`. The frozen
acquisition script raised `kinematic_holdout_center_hill_persistence_prior_missing`
before writing an outcome directory, outcome report, or score.

The protocol had already frozen these rules:

- missing outcomes are omitted without imputation;
- every prediction and baseline uses one common complete-case mask per system;
- persistence at time `t` requires the immediately previous complete hourly
  observation;
- each system needs at least 600 scored hours.

The scorer implements those rules and can omit a row whose immediately previous
observation is missing. The acquisition script's unconditional first-prior
requirement was therefore stricter than, and inconsistent with, the protocol.

## Decision

Do not rerun, revise, postprocess, or replace either sealed prediction.

Use a separately audited recovery acquisition that retains a missing prior as
missing, writes an empty CSV value, performs no imputation, and leaves the
predeclared scoring mask, metrics, minimum sample count, persistence baseline,
and accuracy gates unchanged. The recovery must reverify both prediction hashes
and the joint seal before and after the USGS requests.

## Claim effect

The resulting score remains an outcome-inaccessible test of the already sealed
predictions, but the end-to-end process is not a pristine frozen-code
confirmatory run because recovery acquisition code was added after the first
outcome response. Any machine-generated strict-conformance flag that does not
account for this recovery must be read as superseded by this ADR.

The score may support diagnosis and the next kernel decision, but it cannot by
itself admit the operator form or establish full Geospatial Kernel validation.
