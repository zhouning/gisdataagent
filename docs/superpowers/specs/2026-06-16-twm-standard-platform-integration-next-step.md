# TWM 标准平台集成下一步

- 日期：2026-06-16
- 目标：把自然资源“一张图”TWM 核心标准契约接入 GIS Data Agent 标准全生命周期平台

## 主线关系

TWM 的主线仍然是：角色绑定 -> 状态构建 -> 规则推理 -> 多模态证据 -> 复核闭环。

GIS Data Agent 标准平台的角色是：为 TWM 提供可审定、可发布、可派生、可回滚的数据标准治理底座。

因此，下一步不是另起一条线，而是把已经形成的 TWM 标准契约导入平台，让平台接管后续的标准生命周期。

## 已完成

1. TWM 一张图核心角色契约已结构化为 JSON。
2. TWM 测试数据包已补齐标准字段镜像。
3. QA 已按标准契约执行并通过。
4. 真实 Sentinel-2 影像已接入并作为多模态证据保留。
5. 村规划标准结构样例包 `twm_one_map_village_standard_sample` 已生成并通过 QA。

## 2026-06-16 验证结果

已完成 Docker/PostGIS 环境中的写库和派生闭环验证。

导入标准版本：

| 项 | 值 |
|---|---|
| `doc_code` | `NR_ONE_MAP_TWM_CORE_2026` |
| `version_label` | `2026-06-16-draft` |
| `status` | `released` |
| `document_id` | `18a1e1f0-b3b4-496e-97c7-20e7024f17c6` |
| `version_id` | `4a979e97-9d4c-43da-bfc0-c14a700a5321` |

写入计数：

| 标准平台表 | 数量 |
|---|---:|
| `std_clause` | 9 |
| `std_data_element` | 174 |
| `std_value_domain` | 29 |
| `std_value_domain_item` | 53 |

角色到运行表绑定：

| `bound_table` | 字段数 |
|---|---:|
| `parcel_current` | 27 |
| `synthetic_pbf` | 33 |
| `synthetic_eco_redline` | 19 |
| `synthetic_urban_boundary` | 11 |
| `synthetic_planning_zones` | 7 |
| `synthetic_projects` | 21 |
| `approval_records` | 18 |
| `enforcement_events` | 15 |
| `metadata_vector` | 23 |

派生结果：

| 派生策略 | 状态 | 新增 |
|---|---|---:|
| `to_semantic_hint` | ok | 174 |
| `to_value_semantics` | ok | 29 |
| `to_qc_rule` | ok | 135 |
| `to_defect_code` | ok | 135 |
| `to_data_model` | ok | 1 |
| `to_synonym` | ok | 0 |

`std_data_model_snapshot` 已生成 active 快照：9 个实体、174 个属性、122 个约束。

## 新增脚本

```text
scripts/import_twm_standard_contracts.py
```

默认 dry-run。

应用写库：

```bash
.venv/bin/python scripts/import_twm_standard_contracts.py --apply --derive
```

生成导入计划：

```bash
.venv/bin/python scripts/import_twm_standard_contracts.py
```

## 环境修复

本次验证发现本机 Docker 初始化缺少 `uuid-ossp` 扩展，导致 `uuid_generate_v4()` 相关的标准平台迁移无法在新环境稳定执行。已补充：

```text
docker-db-init.sql
data_agent/migrations/070_create_extension_ltree.sql
```

## 后续开发项

1. `to_qc_rule` 当前将 `bound_table.bound_column` 编码在 `rule_name` 和 `std_derived_link` 中，`config` 只保留检查参数。TWM 规则执行器可解析 `rule_name` 使用，但建议后续把 `bound_table/bound_column` 也显式写入 `config`，便于直接执行和审计。
2. 增加 TWM 运行态导入器：从标准平台 `std_data_model_snapshot`、`agent_semantic_hints`、`agent_quality_rules` 拉取当前 released 标准版本，驱动数据绑定、QA 和状态构建。
3. 增加真实权威数据替换演练：用同构 fixture 先验证角色绑定、字段映射、QA 和证据链替换流程，未来接入政府权威库时不改 TWM 核心逻辑。

## 标准结构样例包验证

已新增：

```text
scripts/generate_twm_village_standard_sample.py
data_agent/test_data/twm_one_map_village_standard_sample/
```

该包来自标准材料中的和平村、斑竹村村规划汇交样例，保留 `JQDLTB/TDGHDL/JSYDGZQ/STBHHX/YBD/EJYSLD/LSWH/STHFQ` 等源结构，并补齐 TWM 角色契约字段。QA 结果：

| 角色 | 必填字段覆盖 |
|---|---:|
| `parcel_current` | 14/14 |
| `pbf` | 19/19 |
| `eco_redline` | 12/12 |
| `urban_boundary` | 11/11 |
| `planning_zone` | 7/7 |
| `project` | 8/8 |
| `approval` | 8/8 |
| `enforcement` | 15/15 |
| `metadata_vector` | 12/12 |

这说明 TWM 的数据基础已经有三条互补基线：

| 数据包 | 用途 |
|---|---|
| `twm_bishan_demo` | 快速开发、前端预览、端到端回归 |
| `twm_bishan_multi_admin_eval` | 跨乡镇评测、边界项目、MMFE 压测 |
| `twm_one_map_village_standard_sample` | 自然资源一张图/村规划汇交结构兼容性回归 |

下一步重点应从“继续补数据”转为“让 TWM 运行态消费这些数据契约和标准平台派生物”。
