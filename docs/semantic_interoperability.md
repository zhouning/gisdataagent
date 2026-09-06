# GIS Data Agent 语义互操作边界

更新时间：2026-09-06

## 结论

Liveability v37 和 Makani v8 的权威运行格式仍分别是：

- `gda.ontology-runtime-overlay.v1`：由源库/表卡反向生成的本体 overlay；
- `gda.multilingual-virtual-semantic-layer.v1`：面向受治理问数运行时的多语言语义层。

从本轮开始，二者可以通过 `data_agent.semantic_interop` 做标准投影和显式导入：

| 对象 | 导出 | 导入 | 语义 |
|---|---|---|---|
| 本体 overlay | RDF 1.1 Turtle、JSON-LD | Turtle、JSON-LD | OWL Class/DatatypeProperty、SKOS 标签和值域、SHACL 基础约束 |
| 语义层 | RDF 1.1 Turtle、JSON-LD、YAML | Turtle、JSON-LD | 业务资产/技术绑定、字段、关系、指标的标准读投影 |
| 语义层 | Apache Ossie Core Metadata YAML `0.2.0.dev0` | Apache Ossie YAML | `semantic_model/datasets/fields/relationships/metrics` 投影 |

标准文件不是可直接执行的问数配置。执行前仍必须经过 source fingerprint、绑定、版本、审核
状态、关系/指标合同和只读门禁。严格导入要求文件含有 GDA 扩展载荷；没有扩展载荷的普通
OWL/RDF/Ossie 文件只能以 `projection-only` 导入，并自动标为不可执行。

## Apache Ossie 映射

Apache Ossie Core Metadata Specification 当前为 incubating 草案，仓库实现按
`https://github.com/apache/ossie/blob/main/core-spec/spec.md` 的 `0.2.0.dev0` 结构进行映射：

- 语义资产/技术表绑定 -> `datasets.name/source`；
- 字段 -> `fields.name/expression/dimension/label/description/datatype`；
- 时间字段 -> `dimension.is_time`，不从时间角色反推物理类型；
- 审核状态、物理字段、技术类型、值域、空间角色 -> `custom_extensions: vendor_name: GDA`；
- 关系 -> `relationships.from/to/from_columns/to_columns`，不能由空间关系冒充外键；
- 指标合同 -> ANSI SQL `metrics.expression`，无法安全表达的合同留在 GDA 扩展中；
- source_id、数据库名、发现/配置 fingerprint、activation gate、answerability policy 和
  完整原始运行时 JSON -> 顶层/模型级 GDA 扩展。

因此 Ossie 互操作解决的是语义模型交换，不会替代 GDA 的 GIS 空间谓词、来源治理、审核和
执行策略。Ossie 草案变更时应先锁定版本，再更新适配器和合同测试。

## 命令行

```bash
# 导出本体
python -m data_agent.semantic_interop export \
  --kind ontology --format turtle \
  --input <ontology.json> --output <ontology.ttl>

# 导出语义层到 Ossie
python -m data_agent.semantic_interop export \
  --kind semantic-layer --format ossie-yaml \
  --input <semantic-layer.json> --output <semantic-model.yaml>

# 严格回读并验证 Turtle/JSON-LD 无损
python -m data_agent.semantic_interop validate \
  --input <semantic-layer.json> --format turtle --format json-ld

# 普通外部 Ossie 只能以投影模式导入，随后由治理流程绑定和审核
python -m data_agent.semantic_interop import \
  --kind semantic-layer --format ossie-yaml --mode projection-only \
  --input <external.yaml> --output <imported-runtime.json>
```

## 页面操作

现有“语义层”工作区和“本体模型”页面均提供“标准互操作”操作区，不新增独立入口：

- 选择 `Liveability` 或 `Makani`，选择“语义层”或“本体模型”，再选择目标格式即可下载当前经过
  checksum 校验的发布快照；
- 语义层可导出 Apache Ossie YAML、RDF Turtle、JSON-LD、GDA YAML/JSON；本体模型可导出 RDF
  Turtle、JSON-LD、GDA JSON；
- 导入支持对应格式的文件上传。上传内容先进行解析和格式校验，随后登记为带 SHA-256 的
  `staged_non_executable` 草稿，可在操作区查看最近导入记录；
- 导入不会覆盖当前发布版本，也不会直接进入问数执行。必须经过源绑定、差异检查、业务审核、
  版本发布和执行门禁后，才可能成为运行时语义资产。
- 数据源下拉框来自当前 checksum 校验通过的 artifact bundle（不是页面内的第二份固定目录），
  并随语义工作区当前数据源联动；本体导入仅向 `admin/standard_editor` 开放，语义层导入向
  `admin/analyst` 开放。

对应 API：

```text
GET  /api/semantic/interop/export/{kind}/{source}/{format}
GET  /api/semantic/interop/sources
POST /api/semantic/interop/import
GET  /api/semantic/interop/imports
```

带 GDA 扩展的 Ossie 文件还包含标准核心投影 hash。严格/带扩展回读会同时校验运行时载荷和
`datasets/fields/relationships/metrics` 核心投影；任何人工修改都会被拒绝。普通 RDF/JSON-LD
投影导入会重建可表达的字段、关系和值域/指标信息，但仍统一标为不可执行待审核草稿。

页面原有可直接写入生产语义注册表的旧 JSON 导入入口已移除，避免绕过标准互操作的草稿和治理门禁。

## 已验证资产

2026-09-06 在本机使用当前真实快照进行 Turtle 生成、RDF 解析和 GDA 扩展 hash 回读：

| 资产 | triples | Turtle 大小 | 扩展 hash 回读 |
|---|---:|---:|---|
| Liveability ontology v36 | 74,921 | 11,092,944 bytes | 通过 |
| Liveability semantic v37 | 140,717 | 20,859,514 bytes | 通过 |
| Makani ontology v7 | 409,820 | 46,131,888 bytes | 通过 |
| Makani semantic v8 | 747,101 | 84,537,229 bytes | 通过 |

这些数字证明标准投影和回读链路可用，不等于业务语义已覆盖所有表字段，也不等于两库任意
问法已经全部可回答。`baseline_sql` 仍是默认生产路线，`semantic_ir_experimental` 仍需在
更大范围 benchmark 和重复稳定性证据后再决定是否晋级。
