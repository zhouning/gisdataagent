# UWM (Urban World Model) 技术评审报告

**评审日期**: 2026-07-09
**评审对象**: gisdataagent 项目中的 Urban World Model (UWM) 实现
**评审人**: Claude (Opus 4.8)
**评审范围**: 理论理解、架构设计、代码实现、数据基础

---

## 一、执行摘要

### 1.1 总体评价

UWM 项目在理论框架和架构设计上展现了**高度的严谨性和前瞻性**，成功地将 Geospatial World Model 理论具体化为城市宜居性领域的实例。项目在以下方面表现优秀：

**优势**:
- ✅ **理论基础扎实**: 准确理解并实现了 world model 的核心范式（状态-动作-转移）
- ✅ **架构设计清晰**: Renderer-Simulator-Planner 三元架构边界明确，职责分离
- ✅ **证据纪律严格**: 完整的 claim boundary 体系，数据分级规范
- ✅ **合约机制完善**: 通过 schema validation 强制执行架构约束
- ✅ **空间依赖建模**: 通过图结构、spillover kernel 实现 Tobler 第一定律

**核心问题**:
- ⚠️ **Simulator 仍是 mechanistic placeholder**: 使用硬编码系数，虽有 data-calibrated mechanism table 但本质仍是已知效应回放
- ⚠️ **Graph-MDP 基于行政邻接而非真实 mobility**: 当前空间图是拓扑邻接，不是出行时间/交通流
- ⚠️ **缺少真实 policy outcome 验证**: 所有优越性声明都基于 simulator replay 或 proxy target
- ⚠️ **部分模块存在 demo 性质实现**: 如 scene_state 的 scenario controls 使用简单线性公式
- ⚠️ **数据覆盖不完整**: 关键角色如 travel-time、真实人口脆弱性、站点校准空气质量仍缺失

### 1.2 核心发现

**架构层面**:
1. UWM 已经建立了完整的 world model 工程骨架，不是简单的宜居性指数包装
2. Renderer-Simulator-Planner 严格遵守了职责边界，planner 必须消费 simulator trace
3. 证据门控体系完整，但在实践中部分模块可能绕过严格验证

**实现层面**:
1. Renderer 实现了观测算子合约，但对 object-field duality 和多尺度系统的处理较浅
2. Simulator 的 action-conditioned transition 存在，但动力学模型是 mechanistic 而非 learned
3. Planner 严格基于 rollout trace，但评分函数较简单
4. Graph-MDP 实现了完整的状态-动作-转移轨迹，但空间图是行政邻接代理

**数据层面**:
1. Manifest 体系完善，75 行资产，18 real + 48 public_proxy + 2 fitted_proxy
2. 数据分级严格（real/public_proxy/fitted_proxy/semi_synthetic/synthetic）
3. 关键数据缺口：travel-time surface、权威人口、站点校准空气质量、真实政策 outcome

---

## 二、Geospatial World Model 理论评估

### 2.1 核心概念理解

**评估**: ✅ **优秀**

UWM 准确理解了 Geospatial World Model 的核心特征：

1. **状态-动作-转移范式**:
   - 文档明确定义：`z_t = Encoder(O_t, G)`, `z_t+1 = Dynamics(z_t, a_t, e_t, G)`, `y_t+k = Decoder(z_t+k)`
   - 代码实现：`renderer.py` 生成 `UwmCanonicalObservation`, `simulator.py` 执行 `action-conditioned rollout`, `planner.py` 消费 `simulator trace`

2. **Tobler 第一定律的结构化实现**:
   - 空间邻接图：通过 `admin_spatial_adjacency_graph` 表达 "近的更相关"
   - 地理相似度：通过 `geographic_similarity_kernel` 补充 "配置相似的也可能有相似过程"
   - 空间溢出：通过 `spatial_spillover_kernel` 实现干预的邻域传播

**证据**: `docs/uwm-geospatial-world-model-geographic-knowledge-integration-2026-07-08.md`

```text
UWM 对这一点的实现不是口头引用，而是把"近的更相关"变成可计算的空间关系、
状态更新机制和规划约束。
```

### 2.2 与传统宜居性分析的区别

**评估**: ✅ **清晰**

文档和代码都清楚地区分了 UWM 与传统方法：

| 维度 | 传统宜居性评价 | UWM | 代码证据 |
|------|---------------|-----|---------|
| 输出 | 静态分数 | 状态+转移+不确定性 | `simulator.py:188-214` |
| 动作 | 无 | action_sequence | `simulator.py:104-176` |
| 推演 | 无 | rollout trace | `simulator.py:28` |
| 证据 | 无分级 | evidence_grade + claim_boundary | `contracts.py:13-19` |

**代码证据**: `baseline.py:8-17`

```python
def compute_traditional_livability_baseline(...):
    """This is intentionally not a world model. It has no action-conditioned
    transition, no rollout and no evidence gate; UWM must beat this baseline
    on dynamic and counterfactual tasks later."""
```


---

## 三、架构评审

### 3.1 Renderer 架构

**评估**: ✅ **架构正确** | ⚠️ **实现深度不足**

#### 3.1.1 架构优势

1. **职责定位准确**: Renderer 确实是 "观测算子" 而非地图渲染器
   ```python
   # renderer.py:12-24
   def build_canonical_observation_from_state_input(...) -> dict[str, Any]:
       """Build `UwmCanonicalObservation.v1` from `mmfe.uwm_state_input.v1`.
       This is an observation function, not a simulator."""
   ```

2. **合约完整**: `UwmCanonicalObservation.v1` 包含所有必需字段
   - `spatial_units`, `object_layers`, `raster_features`, `graph_edges`
   - `quality_flags`, `synthetic_flags`, `provenance`, `claim_boundary`
   - `renderer_trace`

3. **证据链保留**: synthetic_flags 和 claim_boundary 贯穿整个管线

#### 3.1.2 架构问题

**问题 1: Object-Field Duality 处理较浅**

- **现状**: Renderer 通过 `_is_object_layer()` 简单区分 object vs field
  ```python
  # renderer.py:112-119
  def _is_object_layer(row: dict[str, Any]) -> bool:
      object_type = str(row.get("object_type") or "").lower()
      if object_type in {"raster", "grid", "field"}:
          return False
      return True
  ```

- **问题**: 这是基于 type hint 的简单分类，没有深入处理 object-field 的交互和转换

**问题 2: 多尺度系统表达不足**

- **现状**: `spatial_units` 只是一个列表，没有显式的尺度层级和聚合关系
- **文档承诺**: "UWM 需要处理 MAUP、尺度偏差和聚合误差。Renderer 必须显式记录空间单元、尺度、聚合方法和时间窗口。"
- **差距**: 当前实现缺少 `scale_hierarchy`, `aggregation_method`, `maup_risk_flag`

**问题 3: 城市图构建质量有限**

- **现状**: `graph_edges` 只记录 edge summary，没有完整的 edge attributes
  ```python
  # renderer.py:140-149
  def _build_graph_edges(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
      return [{
          "edge_type": row.get("semantic_relation_type"),
          "uwm_usage": row.get("uwm_usage"),
          "relation_count": row.get("relation_count", 1),
      } for row in relations if isinstance(row, dict)]
  ```

- **问题**: 缺少具体的 source/target node, edge weight, distance, travel-time 等关键属性

### 3.2 Simulator 架构

**评估**: ⚠️ **架构正确但动力学模型是 placeholder**

#### 3.2.1 架构优势

1. **Action-Conditioned Transition 存在**
   ```python
   # simulator.py:28
   def simulate_livability_rollout(
       observation: dict[str, Any],
       action_sequence: list[dict[str, Any]],
       ...
   ) -> dict[str, Any]:
   ```

2. **多目标输出完整**
   - `heat_risk_delta`, `air_pollution_exposure_delta`, `service_accessibility_delta`, `equity_delta`, `livability_delta`

3. **不确定性量化**
   ```python
   # simulator.py:463-470
   def _uncertainty_interval(livability_delta: float, observation: dict[str, Any]):
       width = max(0.02, abs(livability_delta) * 0.35)
       if "public_proxy" in statuses:
           width += 0.02
       ...
   ```

4. **Evidence Grade 严格**
   ```python
   # simulator.py:441-448
   def _evidence_grade(observation: dict[str, Any]) -> str:
       if synthetic_statuses.intersection({"synthetic", "semi_synthetic", "smoke_only"}):
           return "exploratory_only"
       return "bounded_support"
   ```

#### 3.2.2 核心问题

**问题 1: Mechanistic Backend 是 Hardcoded 已知效应**

```python
# simulator.py:308-336
def _action_effect(action_type: str, intensity: float, scenario: dict[str, Any], ...):
    if action_key in {"increase_green", "increase_green_infrastructure", "urban_greening"}:
        return {
            "heat_risk_delta": -0.18 * intensity * heat_multiplier,
            "air_pollution_exposure_delta": -0.05 * intensity * air_multiplier,
            "service_accessibility_delta": 0.02 * intensity,
            "equity_delta": 0.04 * intensity * vulnerability_multiplier,
        }
    # ... 其他 action 也是 hardcoded coefficients
```

- **问题**: 这些系数（-0.18, -0.05, 0.02, 0.04）是 hardcoded 的，不是从数据 learned
- **虽然有 data-calibrated mechanism table**: 但本质上仍是用少量数据调整系数，不是真正的动力学模型
- **文档声明**: "The backend is deliberately transparent and mechanistic: it proves the world-model rollout contract and exposes every assumption"
- **实际情况**: 这是诚实的 placeholder，但离 "learned urban dynamics model" 还很远

**问题 2: Spatial Spillover 实现较简单**

```python
# simulator.py:173-175
for neighbour_id, weight in adjacency.get(unit_id, {}).items():
    if neighbour_id in deltas:
        _accumulate(deltas[neighbour_id], effect, 0.35 * weight)
```

- **问题**: 固定的 0.35 spillover factor，不是从数据 learned
- **虽然有 spatial_spillover_kernel**: 但仍是基于 boundary length 等几何特征，不是从实际传播过程 learned

**问题 3: 没有真正的 State Encoder**

- **现状**: Simulator 直接操作 observation dict，没有编码为 latent state
- **文档承诺**: "z_t = Encoder(O_t, G)"
- **实际情况**: Encoder 只是 identity mapping


### 3.3 Planner 架构

**评估**: ✅ **架构规范** | ⚠️ **评分函数简单**

#### 3.3.1 架构优势

1. **严格消费 Simulator Trace**
   ```python
   # planner.py:13-19
   def build_evidence_gated_plan(
       rollout_traces: list[dict[str, Any]],  # 必须是 simulator output
       ...
   ):
   ```

2. **Hard Constraint 作为 Action Mask**
   ```python
   # planner.py:106-120
   def _constraint_rejection_reason(rollout: dict[str, Any], constraints: dict[str, Any]):
       if rollout.get("evidence_grade") == "not_for_claim":
           return "evidence_grade_not_allowed"
       if constraints.get("require_non_negative_equity") and equity_delta < 0:
           return "negative_equity_delta"
       ...
   ```

3. **推荐和拒绝理由可解释**
   ```python
   # planner.py:69
   "rejected_actions": rejected_actions,  # 包含 reason 字段
   ```

#### 3.3.2 问题

**问题: 评分函数过于简单**

```python
# planner.py:128
score = livability_delta + 0.50 * equity_delta - 0.10 * uncertainty_width
```

- **问题**: 固定的线性权重（1.0, 0.50, -0.10）
- **缺少**: 用户偏好、专家输入、多目标 Pareto frontier

### 3.4 数据基础架构

**评估**: ✅ **Manifest 体系完善** | ⚠️ **数据覆盖不完整**

#### 3.4.1 架构优势

1. **完整的 Manifest 体系**
   - 75 行资产登记
   - 分级体系：real (18) / public_proxy (48) / fitted_proxy (2) / semi_synthetic / synthetic
   - claim_boundary 明确

2. **严格的证据纪律**
   ```python
   # renderer.py:177-185
   def _derive_claim_boundary(role_bindings, manifest_audit):
       if manifest_audit.get("valid") is False:
           return "not_for_claim"
       if statuses.intersection({"synthetic", "semi_synthetic", "smoke_only"}):
           return "exploratory_only"
       ...
   ```

#### 3.4.2 数据缺口

根据 `docs/reports/uwm_data_foundation_manifest.md`，关键缺口包括：

1. **Mobility / Travel Time**
   - 联通通勤 CSV 缺格网几何字典
   - 没有 network travel-time surface
   - 没有真实 OD 面或交通流

2. **真实人口脆弱性**
   - 当前只有区县总量和 GHSL downscaling
   - 缺少乡镇/街道级权威人口
   - 缺少脆弱人群细分（老年、低收入、高暴露）

3. **站点校准空气质量**
   - TAP 是多源融合格网产品，不是站点观测
   - OpenAQ 2024-07 scene 返回 0 measurements
   - 缺少 station-calibrated observed holdout

4. **真实政策 Outcome**
   - 所有验证都基于 simulator replay 或 proxy target
   - 缺少真实城市干预前后的 observed outcome

---

## 四、实现质量评审

### 4.1 生产就绪度评估

**总体评估**: ⚠️ **研究原型阶段，离生产就绪有较大差距**

#### 4.1.1 已达到生产级的部分

1. **Contracts 和 Validation**
   - `contracts.py` 完整定义了 3 个核心 schema
   - Validation 严格，会 reject 不符合规范的 payload

2. **Evidence Gate 纪律**
   - `claim_boundary` 贯穿整个管线
   - `evidence_grade` 强制检查

3. **Trace 机制**
   - `renderer_trace`, `simulator_trace`, `planner_trace` 完整记录决策过程

#### 4.1.2 Demo 性质实现的识别

**Demo 1: Scene State 的 Scenario Controls**

```python
# scene_state.py:207-216
def _scenario_controls(population_context, environmental_context):
    temperature = environmental_context["temperature_2m_mean_avg_c"]
    pm25 = environmental_context["pm25_avg_ugm3"]
    return {
        "heat_stress_multiplier": _clamp(1.0 + max(0.0, temperature - 26.0) / 20.0, 0.8, 1.6),
        "air_pollution_stress_multiplier": _clamp(1.0 + max(0.0, pm25 - 25.0) / 100.0 + ..., 0.8, 1.8),
        "vulnerability_multiplier": _clamp(1.0 + high_population_share * 0.5, 1.0, 1.5),
    }
```

- **问题**: 简单的线性公式，阈值（26.0, 25.0）和系数（1/20, 1/100）是人为设定
- **证据**: 没有 calibration trace 或 data source

**Demo 2: Simulator Action Effect Coefficients**

```python
# simulator.py:308-336
"heat_risk_delta": -0.18 * intensity * heat_multiplier,
```

- **问题**: Hardcoded coefficients
- **虽然**: 文档承诺了 "data-calibrated mechanism table"，但基础 backend 仍是 hardcoded

**Demo 3: Spatial Spillover Factor**

```python
# simulator.py:175
_accumulate(deltas[neighbour_id], effect, 0.35 * weight)
```

- **问题**: 固定的 0.35 spillover factor

#### 4.1.3 关键能力缺失

1. **缺少 Learned Dynamics Model**
   - 当前 simulator 是 mechanistic，不是 learned
   - 文档中提到的 "world-model policy" 只是在 replay data 上 fit ridge regression

2. **缺少 True State Encoder**
   - 没有将 multi-modal observation 编码为 latent state
   - 没有 GNN / Transformer 等深度模型

3. **缺少 Online RL Training**
   - 虽然有 `model_based_rl.py` 和 `livability_graph_drl.py`
   - 但只是 offline value fitting，不是真正的 online PPO/DRL

4. **缺少 Causal Inference Integration**
   - 文档提到 Paper6 / SCCA，但代码中没有实际集成
   - 没有 propensity score, IV, RDD, DiD 等因果识别方法

### 4.2 技术债务清单

1. **Hardcoded Coefficients**
   - 位置: `simulator.py:308-336`, `scene_state.py:207-216`
   - 影响: Simulator 不是真正的 learned model
   - 优先级: 高

2. **行政邻接图 vs 真实 Mobility**
   - 位置: `model_based_rl.py`, Graph-MDP 使用 admin boundary adjacency
   - 影响: 空间图不反映真实 travel-time 或交通流
   - 优先级: 高

3. **简单的 Planner 评分函数**
   - 位置: `planner.py:128`
   - 影响: 不支持多目标 Pareto、用户偏好
   - 优先级: 中

4. **Object-Field Duality 处理浅**
   - 位置: `renderer.py:112-119`
   - 影响: 不能深入处理 object-field 交互
   - 优先级: 中

5. **多尺度系统表达不足**
   - 位置: `renderer.py`, `spatial_units` 结构
   - 影响: 不能显式处理 MAUP 和尺度偏差
   - 优先级: 中


---

## 五、数据基础评审

### 5.1 Manifest 评估

**评估**: ✅ **Manifest 体系完善**

根据 `docs/reports/uwm_data_foundation_manifest.md`：

- **总资产**: 75 行
- **分级**: real (18) / public_proxy (48) / fitted_proxy (2) / restricted_expected (1) / semi_synthetic (3) / synthetic (2)
- **可用**: 55 available
- **Claim ceiling**: fragile

**优势**:
1. 完整的来源、时间、CRS、许可登记
2. 严格的 synthetic_status 分级
3. 明确的 claim_boundary

**问题**:
1. 48 个 public_proxy 占比过高（64%）
2. 只有 18 个 real 资产（24%）
3. Claim ceiling = fragile，说明数据基础仍不足以支撑强结论

### 5.2 数据覆盖度评估

#### 5.2.1 已覆盖的角色

✅ **完整覆盖**:
- 建筑轮廓与楼层（107,452 records）
- OSM roads（50,366 records → 6,762 ways + 45,468 edges）
- 高德 POI（1,194,351 features）
- 百度 AOI（26,292 features）
- 行政单元（1,017 个乡镇/街道）
- 行政空间邻接图（2,847 条边）
- CLCD 2020（280M 像元）
- GHSL 人口与建成区（2020）

⚠️ **Proxy 覆盖**:
- 气象: ERA5, Open-Meteo, GEE ERA5, NOAA ISD (江北站)
- 空气污染: OpenAQ (600 observations), TAP (多源融合), CHAP, CAMS
- 人口: 区县统计 + GHSL downscaling

#### 5.2.2 关键缺口

❌ **缺失或不完整**:
1. **Travel-Time / Mobility**
   - 联通通勤缺格网几何字典
   - 没有 network travel-time surface
   - 没有真实 traffic flow 或 OD outcome

2. **人口脆弱性**
   - 缺少乡镇/街道级权威人口
   - 缺少脆弱人群细分（老年、低收入）
   - 没有 2024 场景人口

3. **站点校准空气质量**
   - TAP 是融合格网产品，不是站点观测
   - OpenAQ 2024-07 scene = 0 measurements
   - 缺少 station-calibrated observed holdout

4. **真实政策 Outcome**
   - 所有验证基于 simulator replay
   - 没有真实城市干预前后对比

5. **服务可达性**
   - OSM service POI 只有 786 个
   - 缺少权威服务清册
   - 缺少 network-based accessibility

### 5.3 证据等级体系评估

**评估**: ✅ **证据分级体系严格且贯穿始终**

#### 5.3.1 证据等级定义

```python
# contracts.py:13-19
_EVIDENCE_GRADES = {
    "core_support",
    "bounded_support",
    "fragile",
    "exploratory_only",
    "not_for_claim",
}
```

#### 5.3.2 降级机制

```python
# renderer.py:177-185
def _derive_claim_boundary(...):
    if manifest_audit.get("valid") is False:
        return "not_for_claim"
    if statuses.intersection({"synthetic", "semi_synthetic", "smoke_only"}):
        return "exploratory_only"
    if statuses.intersection({"public_proxy", "restricted_expected"}):
        return "bounded_support"
    return "bounded_support"
```

#### 5.3.3 贯穿整个管线

- Renderer: 根据 synthetic_flags 设置 claim_boundary
- Simulator: 继承 observation 的 evidence_grade
- Planner: 只接受符合 constraints 的 evidence_grade

**优势**: 严格的证据纪律，防止不当升级

---

## 六、Graph-MDP / Model-based RL 评审

### 6.1 Graph-MDP 实现评估

**评估**: ✅ **完整的 MDP 骨架** | ⚠️ **空间图是行政邻接代理**

#### 6.1.1 优势

1. **完整的 MDP 5-tuple**
   - State: `graph_mdp_state` with nodes + edges
   - Action: `action_types` with masks
   - Transition: `simulator.simulate_livability_rollout`
   - Reward: `livability_delta`
   - Terminal: 隐式（fixed horizon）

2. **Replay Dataset 规范**
   ```python
   # model_based_rl.py:29
   GRAPH_MDP_REPLAY_DATASET_SCHEMA = "uwm.graph_mdp_replay_dataset.v1"
   ```

3. **Offline Value Model**
   - 在 355 条 replay transitions 上训练 ridge value model
   - Holdout MAE = 0.000165326 vs train-mean baseline MAE = 0.002418188

#### 6.1.2 核心问题

**问题 1: 空间图是行政边界邻接，不是真实 Mobility**

```python
# model_based_rl.py:60-71
if admin_spatial_graph:
    graph_edges = _spatial_edges_for_units(admin_spatial_graph, ...)
    graph_trace = {
        "edge_type": "admin_boundary_adjacency",
    }
```

- **现状**: 使用 `admin_boundary_adjacency`（2,847 条边）
- **问题**: 这是拓扑邻接，不反映 travel-time、道路连通、出行成本
- **文档警告**: "graph edges are induced from administrative boundary adjacency, not mobility flow"

**问题 2: Offline RL 不是 Online RL**

```python
# offline_world_model_policy.py
```

- **现状**: 在 simulator replay data 上 fit ridge regression
- **问题**: 不是真正的 online PPO/DRL，不能与环境交互学习

**问题 3: Known-Effect Simulator Replay 不是 Observed Outcome**

- 所有 advantage 都基于 simulator replay：
  - Best 2-step reward = 0.012346806
  - Static single-step reward = 0.001439757
  - Advantage = 0.010907049

- **问题**: 这是在 known-effect mechanistic simulator 上的优势，不是在真实 policy outcome 上的优势

### 6.2 Geographic Similarity Kernel 评估

**评估**: ✅ **有价值的补充** | 实现规范

**代码**: `geographic_similarity_kernel.py`

**内容**: 基于服务、道路、暴露、宜居需求配置生成 kNN 相似边

**结果**:
- 1,017 个 panel units
- 5,085 条相似边
- 4,835 条非邻接相似边
- 旋转目标相似度控制通过
- 不使用坐标作为相似度特征

**价值**: 补充了 "地理配置相似的地方可能有相似过程" 的建模假设

---

## 七、评估与验证体系评审

### 7.1 Baseline 完整性

**评估**: ✅ **传统 baseline 规范**

```python
# baseline.py:8-63
def compute_traditional_livability_baseline(...):
    """Compute a static weighted-indicator livability baseline.
    This is intentionally not a world model."""
```

**优势**:
1. 明确标注 `action_conditioned: False`, `dynamic_rollout: False`
2. 提供 limitations 列表
3. 输出可解释的 components

### 7.2 Holdout 规范性

**评估**: ✅ **OpenAQ Temporal Holdout 规范** | ⚠️ **其他 holdout 不足**

#### 7.2.1 OpenAQ Temporal Benchmark

**代码**: `openaq_temporal_benchmark.py`

**结果**:
- 600 observations, 6 pollutants
- 180 holdout points
- Dynamic wins vs static_train_mean: 150/180
- Sign test p-value: 3.17e-23 (vs train_mean), 7.02e-28 (vs last_observation)
- PM2.5 dynamic MAE = 2.4 vs best static MAE = 9.466667
- Ordered-vs-shuffled temporal control passed on 6/6 pollutants

**评价**: 这是**真实观测 holdout**，证明了 UWM 在时序状态预测上的优势

#### 7.2.2 其他 Holdout 的不足

1. **TAP External Dynamics Holdout**
   - 10,000 grid series / 40,000 holdout points
   - Residual-delta MAE = 7.003808 vs adaptive baseline = 7.011689
   - **问题**: Neighbor shuffle 负控不变差，不支持空间归因
   - **结论**: Bounded temporal transition，不支持 spatial claim

2. **Station-Aligned Air Quality Holdout**
   - OpenAQ 上清寺站 100 条 PM2.5
   - **问题**: 2024-07 scene = 0 measurements，不能解除 scene gate

3. **Scene-Aligned Gridded PM2.5 Holdout**
   - CHAP admin representative points + TAP daily PM2.5
   - **问题**: 只支持 gridded state-reconstruction，不是 station-calibrated


### 7.3 Negative Control

**评估**: ✅ **部分负控规范** | ⚠️ **覆盖不完整**

#### 7.3.1 已有的负控

1. **OpenAQ Temporal Ordered vs Shuffled**
   - 通过：6/6 污染物时间顺序负控
   - 证明：模型依赖真实时间顺序

2. **Scene-Aligned PM2.5 Reverse-Coordinate Shuffle**
   - 通过：空间坐标旋转负控
   - 证明：空间消息重建有效

3. **TAP Neighbor Shuffle**
   - **未通过**：neighbor shuffle 不变差
   - 证明：当前不支持空间归因 claim

#### 7.3.2 缺失的负控

1. **Placebo Action Control**: 没有 placebo action 验证
2. **Spatial Randomization**: 缺少全面的空间随机化负控
3. **Confounding Control**: 缺少混淆因子控制

### 7.4 Evidence Gate 严格性

**评估**: ✅ **架构层面严格** | ⚠️ **实践中可能绕过**

#### 7.4.1 架构保障

1. **Contracts 强制验证**
   ```python
   # contracts.py
   def validate_uwm_observation(payload)
   def validate_uwm_rollout_trace(payload)
   def validate_uwm_plan_package(payload)
   ```

2. **Evidence Grade 传播**
   - Renderer → Simulator → Planner
   - 每个阶段都检查并可能降级

3. **Claim Boundary 明确**
   - 每个输出都有 `claim_boundary.max_claim_level`

#### 7.4.2 潜在绕过风险

1. **Hardcoded Coefficients 绕过数据验证**
   - Simulator 使用 hardcoded coefficients，虽然文档诚实声明，但仍然是绕过 data-driven 验证

2. **Proxy Target 可能被误用**
   - Admin livability proxy 只应用于 bounded research，不应升级为 policy claim

3. **Synthetic Data 边界可能模糊**
   - Semi-synthetic scene PM2.5 虽标注为 exploratory，但在管线中可能被混用

---

## 八、改进方案

### 8.1 架构优化建议

#### 8.1.1 优先级 1 (高) - 关键能力补强

**1. 从 Mechanistic 到 Learned Simulator**

**当前问题**:
```python
# simulator.py:308
"heat_risk_delta": -0.18 * intensity * heat_multiplier,  # hardcoded
```

**改进方案**:
- **短期**: 扩展 data-calibrated mechanism table，从更多真实案例校准系数
- **中期**: 训练 spatiotemporal dynamics model (GNN, Transformer)
- **长期**: 构建 end-to-end learned world model with self-supervised learning

**实施路径**:
1. 收集历史城市干预数据（增绿、交通减排、服务补点）
2. 构建 intervention-outcome paired dataset
3. 训练 action-conditioned transition model
4. 验证 learned dynamics 优于 mechanistic baseline

**代码位置**: `simulator.py`, 新增 `learned_dynamics.py`

---

**2. 从行政邻接到真实 Mobility 图**

**当前问题**:
```python
# model_based_rl.py:60-71
graph_edges = _spatial_edges_for_units(admin_spatial_graph, ...)
# edge_type: "admin_boundary_adjacency"  # 不是 travel-time
```

**改进方案**:
- **短期**: 基于 OSM road network 构建 network distance graph
- **中期**: 整合 travel-time estimation (speed limits, road types)
- **长期**: 使用真实 OD 数据或运营商数据构建 mobility flow graph

**实施路径**:
1. 完善 OSM road network (已有 45,468 edges)
2. 添加 edge attributes: distance, estimated_travel_time, road_type
3. 构建 network-based accessibility matrix
4. 替换 Graph-MDP 中的 admin adjacency

**代码位置**: `model_based_rl.py`, 新增 `mobility_graph_builder.py`

---

**3. 补充真实 Policy Outcome 验证**

**当前问题**:
- 所有 advantage 基于 simulator replay
- 缺少真实城市干预前后对比

**改进方案**:
- **短期**: 收集历史案例，构建 before-after comparison
- **中期**: 建立 quasi-experimental design (DiD, RDD, IV)
- **长期**: 开展真实试点，收集 observed outcome

**实施路径**:
1. 识别历史干预案例（增绿项目、交通管控、服务补点）
2. 收集干预前后数据（空气质量、热环境、人群活动）
3. 构建 observed outcome holdout
4. 比较 UWM prediction vs observed outcome

**代码位置**: 新增 `policy_outcome_validator.py`

---

#### 8.1.2 优先级 2 (中) - 实现深度提升

**4. 增强 Renderer 的 Object-Field 处理**

**改进方案**:
- 添加 object-field 交互建模
- 实现 field-to-object aggregation (zonal statistics)
- 实现 object-to-field rasterization
- 显式记录 scale hierarchy 和 MAUP risk

**代码位置**: `renderer.py`, 新增 `object_field_fusion.py`

---

**5. 改进 Planner 评分函数**

**当前问题**:
```python
# planner.py:128
score = livability_delta + 0.5 * equity_delta - 0.1 * uncertainty_width
```

**改进方案**:
- 从固定权重到用户偏好参数化
- 实现多目标 Pareto frontier
- 添加专家规则和业务约束
- 支持交互式权重调整

**代码位置**: `planner.py`, 新增 `multi_objective_planner.py`

---

**6. 集成因果推断**

**改进方案**:
- 整合 Paper6/SCCA 能力
- 添加 propensity score matching
- 实现 instrumental variables
- 支持 difference-in-differences
- 构建 regression discontinuity design

**代码位置**: 新增 `causal_inference/` module

---

#### 8.1.3 优先级 3 (中) - 数据补强

**7. 补充 Travel-Time Surface**

**数据需求**:
- OSM road network 几何字典 ✅ (已有 45,468 edges)
- Road speed estimates (from OSM road types)
- Network-based travel-time matrix

**实施路径**:
1. 为 OSM roads 添加 speed estimates
2. 构建 network travel-time calculator
3. 生成 admin-to-admin travel-time matrix

---

**8. 补充权威人口脆弱性**

**数据需求**:
- 乡镇/街道级权威人口（当前只有区县）
- 年龄结构（老年人口比例）
- 收入水平或社会经济指标
- 2024 场景人口（当前只有 2021）

**实施路径**:
1. 从统计部门获取乡镇/街道人口
2. 整合人口普查或抽样调查数据
3. 构建脆弱性指标体系

---

**9. 补充站点校准空气质量**

**数据需求**:
- 重庆市环境监测站点 2024 观测数据
- Station-model calibration dataset
- Scene-aligned observed holdout

**实施路径**:
1. 获取环境监测站点数据
2. 构建 station-grid alignment
3. 校准 TAP/CHAP gridded products
4. 生成 station-calibrated holdout

---

### 8.2 实施优先级建议

**Phase 1 (3-6 个月) - 关键能力补强**:
1. ✅ 扩展 data-calibrated mechanism table
2. ✅ 构建 network-based mobility graph
3. ✅ 收集历史干预案例

**Phase 2 (6-12 个月) - 深度模型训练**:
4. 训练 learned dynamics model
5. 构建 observed outcome validator
6. 集成因果推断模块

**Phase 3 (12-18 个月) - 生产就绪**:
7. 完整的数据补强
8. 真实试点验证
9. 生产级部署

---

## 九、结论

### 9.1 总体评价

UWM 项目建立了**完整且严谨的 Geospatial World Model 工程骨架**，在以下方面达到了很高的水平：

1. **理论理解准确** - 正确实现了状态-动作-转移范式
2. **架构设计清晰** - Renderer-Simulator-Planner 职责分离严格
3. **证据纪律严格** - 完整的 claim boundary 和数据分级体系
4. **合约机制完善** - Schema validation 强制执行架构约束

### 9.2 当前状态

**项目处于研究原型阶段**，具备以下特征：

- ✅ 完整的架构骨架
- ✅ 规范的数据管理
- ✅ 严格的证据门控
- ⚠️ Mechanistic simulator (hardcoded coefficients)
- ⚠️ Admin adjacency graph (非真实 mobility)
- ⚠️ 缺少 policy outcome 验证
- ⚠️ 关键数据缺口

### 9.3 核心价值

UWM 的核心价值不在于当前实现的完整性，而在于：

1. **建立了正确的架构范式** - 为城市世界模型的演进提供了坚实基础
2. **形成了严格的证据纪律** - 防止不当升级和过度声称
3. **实现了可验证的工程链条** - 从 renderer 到 planner 的完整管线
4. **提供了清晰的演进路径** - 从 mechanistic 到 learned, 从 proxy 到 real

### 9.4 与文档的对应关系

文档中的承诺与代码实现基本一致，**文档诚实地标注了边界**：

- ✅ 文档明确说明 simulator backend 是 "deliberately transparent and mechanistic"
- ✅ 文档明确区分 "bounded support" vs "core support"
- ✅ 文档明确标注 "observed policy outcome superiority = false"
- ✅ 文档明确列出 limitations 和 remaining gates

**这种诚实的边界标注是项目的优势**，避免了过度承诺。

### 9.5 最终建议

要使 UWM 从研究原型演进到生产就绪，建议：

1. **保持架构纪律** - 不降低 Renderer-Simulator-Planner 的职责边界
2. **保持证据纪律** - 不绕过 evidence gate 和 claim boundary
3. **渐进式演进** - 从 mechanistic → data-calibrated → learned
4. **补充关键数据** - Travel-time, 权威人口, 站点空气质量
5. **构建 policy outcome 验证** - 这是升级到 core support 的必经之路

UWM 已经完成了**最困难的部分 - 建立正确的架构和纪律**。接下来的工作是在这个坚实基础上，逐步补充数据、训练模型、验证效果。

---

**评审完成日期**: 2026-07-09
**评审人**: Claude (Opus 4.8)
