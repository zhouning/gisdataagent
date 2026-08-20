# Derived Artifact Boundary

The local benchmark contains large public/test downloads and customer-side
candidate exports under `online/` and `derived/`. They are intentionally not
part of the public Git history. Only small, non-authoritative contracts and
hash receipts may be committed here:

- `abu_dhabi_data_request_register_v2.json`
- `public_data_acquisition_manifest.json`
- `abu_dhabi_data_request_readiness_v2.json`

These records describe what is available and what remains blocked. They do not
contain customer database rows and do not grant model admission.
