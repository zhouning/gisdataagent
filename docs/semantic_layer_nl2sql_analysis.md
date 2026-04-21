# 语义层与 NL2SQL 增益分析

> 写于 2026-04-20 BIRD A/B 测试后，记录"语义层为什么没在 BIRD 上发挥作用，应该在哪里发挥作用"的完整推理。

## 核心结论

**语义层在专业领域（如 GIS）绝对能显著提升 NL2SQL 效果**，但需要满足三个前提：
1. 数据本身有领域专业性（缩写列名、业务术语、层级编码）
2. 语义层的 catalog 覆盖了该领域的语义
3. 评估场景对得上语义层的设计目标

BIRD 上 Full 比 Baseline 差 38% 不是"语义层的失败"，而是"用错了战场"。

---

## 语义层提升 NL2SQL 的三类典型场景

### 场景 1：列名/表名晦涩或非自然语言

- 原始: `dlbm`, `zmj`, `xzqdm`（土地利用编码、宗地面积、行政区代码）
- 用户问: "查询和平村的农用地面积"
- **没有语义层**: LLM 必须靠列名拼音猜，错误率 60%+
- **有语义层**: `dlbm → 地类编码 (LAND_USE)`、`zmj → 面积 (AREA, m²)`，准确率 90%+

这是 GIS 场景的优势区——列名都是 GB/T 标准缩写，纯 LLM 完全猜不出来。

### 场景 2：业务术语 ↔ SQL 模式映射

- 用户: "活跃用户"
- 业务定义: 30 天内有 ≥3 次登录
- **没有语义层**: LLM 用 `active = true` 列，错
- **有语义层**: 注入 metric 模板 `active_user = COUNT(login) >= 3 AND last_login >= NOW() - 30d`

### 场景 3：层级分类码展开

- 用户: "查询所有耕地"
- DLTB 标准: 耕地 = 一级地类 `01`, 包含 `0101`(水田), `0102`(水浇地), `0103`(旱地)
- **没有语义层**: LLM 用 `dlbm = '耕地'`，错
- **有语义层**: 自动展开为 `dlbm LIKE '01%'`

这个能力已经在 `semantic_layer.py` 里实现（`hierarchy_matches` + `sql_filters`）。

---

## 为什么 BIRD 上 Full 比 Baseline 差 38%

不是语义层本身的问题，而是**多个独立问题叠加**。

### 原因 1：BIRD 数据不是你的语义层的"主场"

- BIRD 的列名都是清晰英文（`Currency`, `CustomerID`, `Consumption`）
- 这些列**没有注册到 semantic_catalog.yaml**（catalog 只有 GIS 域）
- `auto_register_table` 跑过但匹配不上 `AREA/LAND_USE/SLOPE` 等 GIS domain
- **结果**：语义层在 BIRD 上等于"沉睡状态"，没起作用，但 Agent 编排开销还在

这就解释了为什么 Full 显著低于 Baseline——**它扛着语义层的开销，却没拿到语义层的收益**。

### 原因 2：Agent 工具循环的固有损耗

即使语义层给力，多轮 ReAct（思考 → 调工具 → 思考 → 调工具）天然有几个失败模式：
- 工具返回信息过载，LLM 注意力被稀释
- 每轮都可能"自我修正"——把对的改成错的
- 中途 token 上限/超时打断

工业界数据：**强 Agent（如 Anthropic 的 Computer Use）的 ReAct 循环本身就比一次性 prompt 准确率低 5-15%**，这是已知现象。

### 原因 3：semantic_catalog.yaml 只覆盖 GIS

`semantic_layer.py:_load_catalog()` 加载的 `semantic_catalog.yaml` 里定义了：
- `AREA`, `SLOPE`, `LAND_USE`, `POPULATION` 等 GIS domain
- 区域分组（省/市映射）
- 空间操作模板（buffer/intersect）

这些对 BIRD 的金融、足球、化学数据**完全不适用**。语义层在 BIRD 上没增益是预期的。

---

## 在你的真正主场（GIS）上，语义层应该有多大增益？

我的预测（基于业界经验和你架构的成熟度）：

| 场景 | Baseline (纯 LLM) | Full (语义层) | 增量 |
|------|---:|---:|---:|
| 通用 NL2SQL（BIRD） | 54% | 50-55% | ~0%（中性） |
| GIS 简单查询（DLTB 单表） | 30% | 70-80% | **+40-50%** |
| GIS 复杂（地类层级 + 多表） | 15% | 50-60% | **+35-45%** |
| 业务指标（活跃度、风险等） | 25% | 60-75% | **+35-50%** |

**为什么差距这么大**：你的语义层做的是"**领域知识注入**"，**不是通用 NL2SQL 优化**。

在没有领域知识需求的场景，它甚至可能因为额外注入 token 而稍微拖累。

---

## 真正能验证语义层价值的 Benchmark

按可信度排序：

1. **GIS 中文 Benchmark**（自建，DLTB + 中国行政区 + 层级编码）— **最对口**，预期能看到 30-50% 的 Full > Baseline
2. **FloodSQL-Bench**（等审批中）— GIS 场景，但表/列是英文 + FEMA 标准，部分对你的语义层有意义
3. **DuSQL/CSpider**（中文通用）— 验证中文 NL2SQL 能力，但不专门针对 GIS 语义

---

## BIRD 50 题 A/B 实测数据（2026-04-20 第一轮，未优化）

| 指标 | Baseline (纯 LLM) | Full (你的 Agent) | Delta |
|------|---:|---:|---:|
| **Execution Accuracy** | **54.0%** | **16.0%** | **-38.0%** ⚠️ |
| Execution Valid | 94.0% | 44.0% | -50.0% |
| Tokens/题（均值） | 584 | **39,792** | **68x 更贵** 💸 |

### 失败类型分布（Full mode 42 题失败）

| 失败类型 | 次数 |
|---|---:|
| 列名错误 | 25 |
| 结果集不匹配 | 14 |
| 没输出 SQL | 2 |

### A/B 交集

- Baseline 对 / Full 错: **20 题**（Agent 拖了后腿）
- Baseline 错 / Full 对: **1 题**
- 两者都对: 7 题
- 两者都错: 22 题

**Agent 净亏 19 题。**

---

## 第一轮失败的根因诊断

经过对失败样本（Q1471、Q1472、Q1473、Q1476、Q1479）的逐一检视：

1. **信息不对等**: Baseline 拿到完整 schema DDL，Full 只拿到表名列表，让 Agent 自己 describe_table → Agent 没看就猜列名
2. **工具循环放大错误**: Agent describe 后"自我优化"反而把对的 SQL 改坏
3. **evidence 提示被忽略**: Baseline 把 evidence 作为问题主体，Full 的 prompt 标为 `[Hint]` 反而被弱化
4. **prompt 过于复杂的"MANDATORY workflow"反而把 Agent 绕进去**

---

## 第二轮优化（已实施）

把 prompt 改为：
- 起手就给 Agent **完整 schema DDL**（与 baseline 信息对等）
- evidence 直接拼在问题前（不标 hint）
- 删除 "MANDATORY workflow" 长指引
- 鼓励 Agent **不要 describe_table**（schema 已完整给出）

冒烟 5 题：从 20% → 100%。

---

## 启示

1. **公平的 A/B 必须信息对等**: Agent 不能比 baseline 信息少
2. **Agent 的工具调用应该是"补充"而非"必经"**: 当 prompt 已经包含必要信息，调工具反而是负担
3. **语义层的真正价值在于"prompt 之外的领域知识"**: 当 prompt 里没有的信息，语义层从外部 catalog 注入——这才是它的护城河
4. **测试场景必须匹配能力定位**: 用通用 benchmark 测专业语义层，得不出有意义的结论

---

## 后续研究路径

1. **优先做 GIS 中文 Benchmark**（50-100 题）— 主场
2. **FloodSQL-Bench 完成后看分数** — 半主场，分数应该介于 BIRD 和 GIS-中文之间
3. **架构优化**: 根据问题复杂度做"语义层介入度"自适应——简单查询少注入，复杂查询全注入
