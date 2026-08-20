# Abu Dhabi Stormwater Data Request Readiness

This audit checks the v2 data-request register against local public artifacts. It does not consume customer database rows and does not open any model gate.

- Requests: **12**
- Customer/authority deliveries received: **0**
- Requests still blocked: **12**
- Requests with usable public proxies: **4**
- Requests with metadata-only/restricted catalog evidence: **1**
- Requests with local but unregistered candidates: **3**
- Admissible proxy files with all delivery metadata present: **0**
- Requests with no public proxy: **4**

| Priority | Request | Customer status | Public evidence | Model use |
|---|---|---|---|---|
| P0 | `coastal-boundary-time-series` | `recorded_waiting_customer_or_authority` | `no_public_proxy` (0 admissible proxy file(s)) | blocked: K0, coastal boundary admission, recession validation, operational prediction |
| P0 | `drainage-network-topology-units` | `recorded_waiting_customer_or_authority` | `local_candidate_unregistered` (0 admissible proxy file(s)) | blocked: K0, engineering SWMM, non-zero coupling, operational counterfactuals |
| P0 | `engineering-surface-vertical-datum` | `recorded_waiting_customer_or_authority` | `local_candidate_unregistered` (0 admissible proxy file(s)) | blocked: K0, ANUGA engineering admission, depth calibration, GWM training labels |
| P0 | `event-rainfall-forcing` | `recorded_waiting_customer_or_authority` | `available_public_proxy` (4 admissible proxy file(s)) | blocked: K0, event calibration, GWM training, city-scale prediction |
| P0 | `pump-gate-operation-history` | `recorded_waiting_customer_or_authority` | `no_public_proxy` (0 admissible proxy file(s)) | blocked: K0, non-zero coupling, hybrid planning, operational GWM |
| P0 | `timed-inundation-observations` | `recorded_waiting_customer_or_authority` | `metadata_only_proxy` (0 admissible proxy file(s)) | blocked: K2, GWM training, impact accuracy, city-scale prediction |
| P1 | `common-geography-overlay-rule` | `recorded_waiting_customer_or_authority` | `available_public_proxy` (1 admissible proxy file(s)) | blocked: per-asset impact, liveability overlay, GWM spatial labels |
| P1 | `historical-events-design-storms` | `recorded_waiting_customer_or_authority` | `available_public_proxy` (3 admissible proxy file(s)) | blocked: GWM generalization, design decision claims, uncertainty calibration |
| P1 | `landcover-infiltration-parameters` | `recorded_waiting_customer_or_authority` | `no_public_proxy` (0 admissible proxy file(s)) | blocked: parameter calibration, design storm reliability |
| P1 | `liveability-exposure-semantics` | `recorded_waiting_customer_or_authority` | `local_candidate_unregistered` (0 admissible proxy file(s)) | blocked: impact overlay, priority ranking, customer-facing exposure claims |
| P1 | `roads-curbs-obstacles-buildings` | `recorded_waiting_customer_or_authority` | `available_public_proxy` (1 admissible proxy file(s)) | blocked: credible road-level depth, surface routing validation |
| P2 | `maintenance-blockage-asset-condition` | `recorded_waiting_customer_or_authority` | `no_public_proxy` (0 admissible proxy file(s)) | blocked: reliability scenarios, failure-aware planning |

## Gate state

K0, traditional-model admission, GWM training, hybrid planner and city-scale prediction claims remain closed. Public files are limited to diagnostic sensitivity, context, or catalog evidence until the customer/authority acceptance checks are completed.
