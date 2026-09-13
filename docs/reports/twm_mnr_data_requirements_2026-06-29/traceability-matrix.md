# TWM 自然资源数据需求追踪矩阵

| 文档章节 | 数据/证据来源 | 追踪说明 |
|---|---|---|
| 最小交付包 | `twm-production-input-data-requirements.md` 第 2 节、`twm_validation_bundle.md` production preflight | observed_history、policy_history、scale_profile 是生产 readiness 的核心输入 |
| observed_history 要求 | `twm-production-input-data-requirements.md` 第 3-12 节 | 字段组、生产候选行、treated/control、时间留出 |
| policy_history 要求 | `twm_validation_bundle.json` policy_history_quality / policy_history_alignment | allowed/blocked、region_policy、region_action_policy、mixed allowed policy coverage |
| scale_profile 要求 | `twm_production_scale_profile_template.json`、`build_production_scale_readiness` 契约 | lakehouse、partition、spatial index、distributed compute、sampling/tiling |
| 数据安全边界 | `twm-production-input-data-requirements.md` 第 14 节 | 不跨环境提交原始几何、逐行属性、敏感 ID、真实内网路径 |
| 当前差距 | `twm_validation_bundle.md` Production Observed-History Preflight / Production Readiness Gate | 当前真实 observed history 和 production scale profile 默认仍 not_provided/review |
| 大数据能力 | `docs/twm-current-handoff.md` TxPoint10M Lakehouse Scale Evidence | 10M 行 lakehouse 能力证据，不等同业务生产准确性 |
