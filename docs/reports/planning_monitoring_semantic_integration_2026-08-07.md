# 规划实施监测模型语义接入与内网部署闸门

**适用版本**：`gda.nr.planning-monitoring.current-state@1.0.0`

**语义合同**：`gda.nr.planning-monitoring.semantic-input.v1@1.0.0`

**本体**：`natural-resource-one-map@2.3.0`

## 本次修正

模型现在有独立的语义输入映射合同：

`data_agent/model_contracts/planning_monitoring_semantic_mapping.v1.json`

该合同把模型输入角色映射到自然资源本体或标准制品，而不是把“智能问数”“报告生成”之类功能建成自然资源本体类：

| 模型角色 | 本体/标准语义引用 | 典型标准代码 |
|---|---|---|
| 建筑 | `gda:nr:class:Building` | `CQNFWJZA`、`r_bld_a` |
| POI | `gda:nr:class:PublicFacility` | `SSGGFWSSD`、`POI` |
| 道路 | `gda:nr:class:Road` | `t_cir_l`、`t_cor_l`、`LCTL` |
| 土地覆盖/利用栅格 | `gda:nr:class:SpatialUnit` + `currentLandUseCode` | `TDLYXZ`、`CLCD` |
| DEM | `SZGCMX` 标准制品及其高程属性 | `SZGCMX`、`GDEM` |

模型指标仍属于模型合同；运行结果保存在治理产物中，语义层只登记概念、属性、版本、引用和血缘，不复制全部业务记录到本体库。

## 运行前闸门

`run_planning_monitoring_evaluation.py` 在读取任何业务记录前执行以下检查：

1. 读取并固定语义映射合同哈希。
2. 校验本体包/权威库可用、语义版本一致、概念和属性存在，记录本体内容哈希。
3. 读取 `ontology_bindings/<binding-id>/binding.json`，校验绑定状态、模式、版本和生产资格。
4. 将绑定目标与 `materialization.json` 按 `target_id`、目标路径或源资产 ID 对齐。
5. 生产模式要求每个被选中的目标都有 `target_sha256`，并与物化声明一致。
6. 校验来源字段到本体属性再到模型字段的映射，例如 `Floor -> gda:nr:property:totalFloorCount -> floor_count`。

生产模式任一项失败会生成 `semantic_gate_report.json` 和 `monitoring_evaluation_report.json`，状态为 `blocked`，CLI 返回码为 `2`，不会生成指标结果。演练模式允许显式的文件名别名回退，但角色会标记为 `name_alias_rehearsal`，结果永远不能生产发布。

## Windows 内网执行

以下命令在随包 Python 环境中执行，不依赖 ArcPy、MCP、容器、数据库或互联网。路径使用 Windows 形式：

```powershell
& .\runtime\python.exe .\scripts\run_planning_monitoring_evaluation.py `
  --materialization D:\GDA_LAKE\materialized\<run-id>\materialization.json `
  --ontology-binding D:\GDA_LAKE\ontology_bindings\<binding-id>\binding.json `
  --ontology-package D:\GDA_CONFIG\ontology\natural_resource_one_map\2.3.0 `
  --authority-mode production `
  --output D:\GDA_LAKE\model\planning-monitoring\<run-id>
```

现场首先应使用 `--authority-mode rehearsal` 完成一批真实数据的接入演练，确认字段、几何、CRS、值域和覆盖率问题；只有标准合同、质量检查和本体绑定都获得正式批准后，才切换到 `production`。

## 重庆样例结果

重庆样例使用了现有的演练绑定。建筑、POI、道路在原绑定中被 ingest 层标记为 `skipped`，因此模型明确记录为 `name_alias_rehearsal`；CLCD 在旧绑定中被暂记为 `SZZSYX`，这不是合格的土地覆盖语义，模型同样拒绝把它当作正式绑定；只有 DEM 保留直接绑定引用。本次同时修复了 2.3.0 本体包中 `shapes.ttl` 的 manifest 哈希和字节数，整包重新校验通过，运行时已能固定加载 2.3.0。重庆结果仍为 `succeeded_with_review` 且 `production_eligible=false`，因为上述四个角色没有正式绑定，而且旧绑定未记录物化目标哈希；系统没有把这批样例伪装成权威宁夏对象。

未来若本体包内容变化，必须重新生成 manifest/绑定并重新计算目标哈希；不能手工删除 `semantic_gate_report.json` 中的阻断或复用旧绑定。

## 部署验收标准

- 生产报告 `semantic_gate.status == "pass"`；
- `ontology.status == "available"`，语义版本与内容哈希已固定；
- 所有实际使用角色的 `role_resolution == "ontology_binding"`；
- 所有绑定目标 `binding_hash_verified == true`；
- `quality_report.status == "pass"`；
- `monitoring_evaluation_report.production_eligible == true`；
- `lineage.json` 同时包含数据目标到本体概念的 `semantically_bound_to` 边和目标到模型/结果的血缘边。

任一条件不满足，都应停留在演练或复核，不得向客户输出正式规划评估结论。
