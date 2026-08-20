# Abu Dhabi Stormwater World Model Data Boundary

This directory contains the public, non-authoritative contracts for the Abu
Dhabi urban stormwater/flood world-model candidate.

The repository intentionally does not contain customer database rows,
credentials, internal database endpoints, private survey data, or bulk raster
and vector downloads. Large public/test artifacts are kept in the local
working dataset and are referenced by manifests and SHA-256 receipts only.

The authoritative production inputs must be supplied by the customer or the
responsible authority. Public and synthetic data may be used only for adapter
tests, pipeline checks, and diagnostic sensitivity analysis. Receiving a file
does not open K0 or admit a traditional model, GWM training, a hybrid planner,
or a city-scale prediction claim.

Relevant small contracts:

- `derived/abu_dhabi_data_request_register_v2.json`
- `derived/public_data_acquisition_manifest.json`
- `derived/abu_dhabi_data_request_readiness_v2.json`

The raw and derived data tree is intentionally excluded from the public code
commit. Recreate it locally using approved, no-login public sources or through
the customer's controlled delivery channel.
