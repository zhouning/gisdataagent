# TWM MMFE Semantic Fusion Bundle

Product: `sfp-twm-dc2a707aabda0c01`

This bundle shows how the prepared TWM validation dataset is consumed as an
MMFE multimodal semantic fusion product. The output is not one flattened GIS
table. It is a semantic bundle that connects layers, standards, policy rules,
evidence, review tasks and optimization summaries.

## Outputs

- `twm_mmfe_business_view.csv`: human-readable one-row business summary.
- `twm_mmfe_field_semantics.csv`: field-level standard aliases, role contracts and TWM binding keys.
- `twm_mmfe_value_domain_audit.csv`: value-level standard domain audit for semantically bound fields.
- `twm_mmfe_standard_sources.csv`: auditable registry of standard authorities, source URLs and acquisition status.
- `twm_mmfe_semantic_relations.csv`: project/parcel/control-line/remote-sensing semantic relations.
- `twm_state_input_contract.json`: state-builder contract for TWM consumption.
- `twm_state_input.json`: TWM-ready state input package derived from the MMFE semantic product.
- `twm_mmfe_semantic_graph.json`: lightweight semantic graph of layers, fields, rules, evidence and objectives.
- `twm_mmfe_semantic_trace_cards.json`: compact semantic trace cards for fields, value domains, standards, rules and objectives.
- `twm_mmfe_semantic_product.json`: MMFE semantic fusion product manifest.
- `twm_mmfe_semantic_vectors.pgvector.json`: pgvector/LanceDB-ready semantic records.
- `twm_mmfe_publish_plan.json`: Iceberg/STAC/vector publish plan.
- `twm_mmfe_stac_item.json`: STAC discovery item.

## What Was Fused

- Layers: 9
- Active standard fields: 266
- Standard sources: 7
- Officially verified standard sources: 1
- Standard sources pending official release evidence: 6
- Field semantic mappings: 274
- Value-domain audits: 6
- Semantic relations: 728
- Rule evaluations: 240
- Review-required rule hits: 92
- Evidence records: 173
- Optimization scenarios: 7
- Legal feasible scenarios: 2
- Semantic graph: 1424 nodes, 3547 edges
- Semantic trace cards: 14

## TWM Consumption Guidance

后续 TWM 不应只直接读取原始数据文件。原始数据仍作为几何和属性事实源，但状态构建、规则解释、证据链、AI 检索和优化输入应优先读取 MMFE 语义融合成果。
