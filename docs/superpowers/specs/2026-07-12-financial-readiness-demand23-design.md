# Financial and Investment Demand 23 Design

## Objective

Implement an evidence-bounded financial and investment readiness product for customer demand 23 without inventing project quantities, prices, capital costs, operating costs, revenues, financing terms, cash flows, NPV, IRR, payback periods or investment recommendations.

## Method Ownership

- Traditional deterministic finance owns accounting identities, discounted-cash-flow formulas, scenario comparison and audit trails.
- UWM may provide verified intervention quantities, implementation timing, asset transitions and uncertainty envelopes as upstream inputs.
- UWM does not generate prices, costs, revenues, discount rates, financing terms or financial returns.
- No financial indicator is computed until all mandatory deterministic inputs pass evidence and unit gates.

## Product Contract

Schema: `uwm.financial_investment_readiness.v1`.

Input channel groups:

- project scope and BOQ
- capital expenditure
- operating expenditure
- revenue and other benefits
- implementation schedule
- financing and discount assumptions
- taxes, subsidies and residual value
- UWM scenario handoff

Each channel includes status, value, unit, evidence reference and blockers. Missing evidence is represented by `status=unavailable` and `value=null`.

## Calculation Gate

The deterministic finance gate contains:

- quantity-price multiplication
- capex aggregation
- opex aggregation
- revenue aggregation
- annual cash-flow construction
- discounted cash flow
- NPV
- IRR
- payback period
- sensitivity analysis
- scenario comparison

All mechanisms remain closed until the required authoritative project data are available. Financial outputs remain null while closed.

## UWM Handoff Gate

UWM scenario outputs may be accepted only when they include bundle identity, scenario identity, baseline and intervention definitions, quantity units, time axis, spatial scope, uncertainty and provenance. Current repository products do not provide a customer-approved project financial handoff, so the gate remains closed.

## Source Assets

Repository financial field standards may be catalogued as data-contract evidence. They are not treated as customer project financial records. Existing roadmap, cross-domain and UWM products may be catalogued as upstream scenario/product capabilities but not as monetary evidence.

## Claim Boundary

Maximum claim: `financial_data_contract_and_deterministic_calculation_readiness`.

Mandatory exclusions:

- field definitions are not financial observations
- POI counts are not revenue
- project areas are not BOQ
- UWM interventions are not costs or benefits
- missing cost is not zero cost
- missing revenue is not zero revenue
- no NPV, IRR, payback, ROI, affordability, bankability or investment recommendation

## Publication

Publish six bundle-consistent files:

- `overview.json`
- `evidence_assets.json`
- `financial_channels.json`
- `data_contracts.json`
- `calculation_gate.json`
- `map.json`

Expose six authenticated API endpoints and an independent `财务与投资证据` tab.
