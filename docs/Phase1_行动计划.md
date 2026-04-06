# GIS Data Agent — Phase 1 行动计划

> 日期：2026-04-07
>
> 目标：三调数据场景的治理闭环演示
>
> 预估周期：4-6 周
>
> 前置文档：A/B/C/D 迭代 1

---

## 0. 验证场景定义

| 项 | 值 |
|---|---|
| 场景 | 第三次全国国土调查（三调）相关数据的治理 |
| 数据样本 | 重庆脱密样例数据（替代山西保密数据） |
| 数据模型 | `自然资源全域数据模型/02统一调查监测.xml`（EA Native XMI） |
| 数据标准 | `自然资源"一张图"数据库体系结构（2）统一调查监测1126.docx` |
| 语义基础 | `data_agent/standards/gis_ontology.yaml`（37 组，需针对三调扩充） |
| 成功标准 | 跑通 UC-05→UC-06→UC-07→UC-10 闭环，产出一份可演示的治理成果报告 |
| 演示对象 | 山西测绘院总工（用重庆数据演示能力，说明可迁移到山西场景） |

---

## 1. Step 0：建产品分支 + 搭骨架（第 1 周前半，2-3 天）

### 1.1 创建分支

```bash
git checkout feat/v12-extensible-platform
git checkout -b feat/product-v1
```

### 1.2 搭建三层目录结构

```
data_agent/
├── knowledge/              ← 知识管理层（新建）
│   ├── __init__.py
│   ├── semantic_vocab.py   # 语义等价库
│   ├── standard_rules.py   # 标准规则库
│   ├── model_repo.py       # 数据模型库
│   └── case_library.py     # 治理案例库（Phase 2+）
│
├── intelligence/           ← 智能交互层（新建）
│   ├── __init__.py
│   ├── model_advisor.py    # UC-05 模型推荐
│   ├── governance_orchestrator.py  # UC-06 治理执行
│   ├── report_generator.py # UC-07 成果报告
│   └── profiler.py         # UC-02 数据画像（Phase 2）
│   └── gap_analyzer.py     # UC-04 标准对照（Phase 2）
│
├── platform/               ← 底座调用层（新建）
│   ├── __init__.py
│   ├── datasource_api.py   # 数据源管理 API 封装
│   ├── metadata_api.py     # 元数据读取 API 封装
│   ├── governance_api.py   # 质检/治理执行 API 封装
│   └── asset_api.py        # 数据资产/数据服务 API 封装
│
├── standards/              ← 保留（知识资产）
│   ├── gis_ontology.yaml
│   └── defect_taxonomy.yaml
│
├── db_engine.py            ← 保留（基础设施）
├── auth.py                 ← 保留
├── user_context.py         ← 保留
├── observability.py        ← 保留
├── intent_router.py        ← 保留（后续改造路由目标）
└── ...
```

### 1.3 从原型分支迁入的模块

| 模块 | 迁入方式 | 说明 |
|------|---------|------|
| `db_engine.py` | 直接复制 | 基础设施，无需改动 |
| `auth.py` | 直接复制 | 基础设施 |
| `user_context.py` | 直接复制 | 基础设施 |
| `observability.py` | 直接复制 | 基础设施 |
| `standards/*.yaml` | 直接复制 | 知识资产 |
| `intent_router.py` | 复制后简化 | 去掉三管线路由，改为治理步骤路由 |
| `semantic_layer.py` | 提取核心匹配逻辑 | 重构进 `knowledge/semantic_vocab.py` |
| CI/CD 配置 | 直接复制 | `.github/workflows/` |
| 测试框架 | 复制模式 | conftest.py + mock 模式 |

### 1.4 更新 CLAUDE.md

加入 C 层约束和三层架构说明（内容见 D-设计改进方案文档第 6 节）。

---

## 2. Step 1：底座对接层（第 1 周后半 ~ 第 2 周，5-7 天）

### 2.1 需要封装的底座 API

按"传统数据平台智能体化策略分析"的路径 A（直接封装 RESTful API），优先封装 Phase 1 需要的接口：

| 模块 | 需要的 API | 用于 |
|------|-----------|------|
| `platform/metadata_api.py` | 读取数据集列表、字段结构、坐标系信息 | UC-05 了解数据现状 |
| `platform/governance_api.py` | 导入数据模型、创建质检任务、执行质检、获取质检结果 | UC-06 执行治理 |
| `platform/asset_api.py` | 登记数据资产、发布数据服务 | UC-06 收尾步骤 |
| `platform/datasource_api.py` | 注册数据源、测试连接 | UC-06 前置 |

### 2.2 封装模式

```python
# platform/governance_api.py 示例结构

class GovernancePlatformAPI:
    """时空数据治理平台 - 治理执行 API 封装"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    async def import_data_model(self, model_config: dict) -> dict:
        """导入数据模型到治理平台"""
        ...

    async def create_quality_check(self, dataset_id: str, rule_set: str) -> str:
        """创建质检任务，返回 task_id"""
        ...

    async def get_quality_result(self, task_id: str) -> dict:
        """获取质检执行结果"""
        ...

    async def execute_data_aggregation(self, source_id: str, target_model: str) -> dict:
        """执行数据汇聚"""
        ...
```

### 2.3 验证标准

能通过 Python 代码调用底座完成以下操作：
- [ ] 读取重庆三调样例数据的元数据（字段列表、记录数、坐标系）
- [ ] 向底座导入一个数据模型
- [ ] 对样例数据执行一次质检并获取结果
- [ ] 将质检通过的数据登记为数据资产

---

## 3. Step 2：知识注入（第 2 ~ 3 周，与 Step 1 并行，7-10 天）

### 3.1 数据模型解析 — `knowledge/model_repo.py`

**输入**：`自然资源全域数据模型/02统一调查监测.xml`（EA Native XMI，802KB）

**处理**：
1. 解析 EA XMI 格式（DTD 定义在 `UML_EA.DTD` 中）
2. 提取：Package 层级（业务域）→ Class 列表（实体对象）→ Attribute 列表（字段定义：名称、类型、长度、必填性、值域约束）
3. 提取：Class 间的 Association / Generalization 关系
4. 输出为 JSON/YAML 结构：

```json
{
  "业务域": "统一调查监测",
  "实体对象": [
    {
      "名称": "地类图斑",
      "英文": "DLTB",
      "字段": [
        {"名称": "DLBM", "中文名": "地类编码", "类型": "VARCHAR(6)", "必填": true, "值域": "引用TD_DLBM"},
        {"名称": "DLMC", "中文名": "地类名称", "类型": "VARCHAR(60)", "必填": true},
        ...
      ],
      "关系": [
        {"类型": "关联", "目标": "行政区", "角色": "所属行政区"}
      ]
    }
  ]
}
```

**这是 AI 做模型推荐的核心输入** — 有了这个结构化的模型定义，LLM 才能把样例数据的字段和目标模型的字段做对比。

### 3.2 数据标准解析 — `knowledge/standard_rules.py`

**输入**：`自然资源"一张图"数据库体系结构（2）统一调查监测1126.docx`（1.8MB）

**处理**：
1. 解析 Word 文档中的表格（通常数据标准文件中的规则以表格形式呈现）
2. 提取：数据表名→字段名→字段类型→值域→约束条件→说明
3. 输出为结构化规则条目：

```json
{
  "标准名称": "自然资源一张图数据库体系结构-统一调查监测",
  "版本": "1126",
  "规则": [
    {
      "适用表": "DLTB",
      "字段": "DLBM",
      "规则类型": "值域规则",
      "规则内容": "必须符合TD_DLBM编码表",
      "严重程度": "A"
    },
    {
      "适用表": "DLTB",
      "字段": "TBMJ",
      "规则类型": "精度规则",
      "规则内容": "面积值精确到0.01平方米",
      "严重程度": "B"
    }
  ]
}
```

### 3.3 语义等价库扩充 — `knowledge/semantic_vocab.py`

**输入**：现有 `gis_ontology.yaml`（37 组）+ 三调业务知识

**处理**：补充三调场景涉及的语义等价关系，例如：

```yaml
# 新增三调相关等价组
- group: land_use_code
  equivalents: [DLBM, 地类编码, land_use_code, dlbm, LandUseCode]
  
- group: land_use_name
  equivalents: [DLMC, 地类名称, land_use_name, dlmc, LandUseName]

- group: parcel_area
  equivalents: [TBMJ, 图斑面积, parcel_area, tbmj, SHAPE_Area]

- group: admin_code
  equivalents: [XZDM, 行政代码, admin_code, xzdm, ZLDWDM]
```

**这是 AI 做字段语义匹配的基础** — 有了这些等价关系，系统才能识别出样例数据中的 `dlbm` 字段就是标准中要求的 `DLBM（地类编码）`。

### 3.4 知识注入验证标准

- [ ] `model_repo.py` 能解析 `02统一调查监测.xml`，输出三调相关的实体对象和字段列表
- [ ] `standard_rules.py` 能解析标准 Word 文档，输出结构化规则条目
- [ ] `semantic_vocab.py` 能匹配样例数据中的字段名到标准字段名（如 `dlbm` → `DLBM/地类编码`）

---

## 4. Step 3：智能交互层 P0 用例（第 3 ~ 5 周，10-14 天）

### 4.1 UC-05 推荐数据模型调整方案 — `intelligence/model_advisor.py`

**流程**：

```
输入：重庆三调样例数据 + 通用调查监测数据模型（来自 model_repo）
  ↓
Step 1：读取样例数据的元数据（通过 platform/metadata_api）
  ↓
Step 2：用 semantic_vocab 做字段语义匹配
  ├── 样例字段 dlbm → 匹配到模型字段 DLBM（地类编码）✓
  ├── 样例字段 unknown_col → 无法匹配 → 标记为"待人工确认"
  └── 模型字段 GDLX（耕地类型）→ 样例中缺失 → 标记为"缺失字段"
  ↓
Step 3：用 standard_rules 检查值域合规性
  ├── DLBM 的值是否在 TD_DLBM 编码表内
  └── TBMJ 的精度是否满足要求
  ↓
Step 4：LLM 综合推理（基于以上结构化分析结果）
  ├── 输入：字段匹配结果 + 值域检查结果 + 模型定义 + 标准规则
  ├── 约束：必须引用知识库中的具体规则，不允许无依据发挥
  └── 输出：模型调整建议清单（JSON 格式）
  ↓
Step 5：操作人员审查确认
```

### 4.2 UC-06 执行数据治理 — `intelligence/governance_orchestrator.py`

**流程**：

```
输入：确认后的模型调整方案
  ↓
Step 1：根据调整方案编排治理步骤
  ├── 数据汇聚：将样例数据按目标模型结构重组
  ├── 数据质检：按标准规则逐条检查
  ├── 数据开发：对不合规项执行修正（如编码转换、字段补全）
  ├── 数据服务：发布治理后的数据
  └── 数据资产：登记为数据资产
  ↓
Step 2：调用 platform/ 层 API 逐步执行
  ↓
Step 3：实时反馈执行进度
  ↓
Step 4：汇总执行结果
```

### 4.3 UC-07 生成治理成果报告 — `intelligence/report_generator.py`

**报告结构**：

```
1. 概述
   - 治理范围（数据集名称、数据量、时间）
   - 治理依据（数据标准名称+版本、数据模型名称+版本）

2. 治理前数据质量
   - 质量指标总览（完整性、一致性、精度、时效性）
   - 主要问题列表

3. 治理方案
   - 模型调整内容
   - 治理步骤和参数

4. 治理后数据质量
   - 质量指标总览（与治理前对比）
   - 质量提升百分比

5. 遗留问题
   - 未能自动修复的问题列表
   - 建议的人工处理方案

附录：
   - 详细质检记录
   - 字段映射表
```

输出格式：Word/PDF（使用 python-docx 生成）。

### 4.4 UC-10 ChatBI

已在并行开发，Phase 1 需要确保能对接治理结果数据。

---

## 5. Step 4：端到端验证 + 演示准备（第 5 ~ 6 周，5-7 天）

### 5.1 端到端流程验证

用重庆三调脱密数据走完：

```
加载样例数据 → 读取元数据 → 语义匹配 → 标准对照 → 生成模型调整建议
→ 人工确认 → 编排治理步骤 → 调用底座执行 → 生成治理成果报告 → ChatBI 展示
```

### 5.2 度量指标采集

| 指标 | 采集方式 |
|------|---------|
| 端到端耗时（人天） | 全流程计时 |
| AI 推荐准确率 | 人工审查 AI 建议的采纳率 |
| 报告生成时间 | 从治理完成到报告输出的时间 |
| 对比基线 | 山西项目同类场景的人工耗时（如果能获取） |

### 5.3 演示准备

- 录制一个 5-10 分钟的演示视频
- 准备一份面向总工的材料：问题→方案→效果→下一步
- 核心信息：**"同样的三调数据治理场景，从 X 人天降低到 Y 人天"**

---

## 6. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| EA XMI 解析复杂度超预期 | 中 | Step 2 延期 | 先只解析三调涉及的实体（DLTB 等），不解析全量模型 |
| 标准 Word 文档格式不规范 | 中 | Step 2 延期 | 先人工提取关键表格为 CSV，再写解析器 |
| 底座 API 粒度不匹配 | 低 | Step 1 延期 | 你管 Java 团队，可以安排他们补接口 |
| LLM 推理质量不够 | 中 | Step 3 效果差 | 严格限制 LLM 只基于知识库推理，不自由发挥；人工兜底 |
| 重庆数据和山西场景差异大 | 低 | 演示说服力不足 | 重点演示能力和流程，弱化具体数据内容 |

---

## 7. Phase 2 预告

Phase 1 验证成功后，Phase 2 的重点是：

- UC-01~UC-04（操作者提效）：自动数据画像 + 自动标准对照
- 知识库扩充：从三调扩展到更多业务域
- 底座对接从路径 A（OpenAPI 直封）演进到路径 B（MCP 重组粒度）
- 治理案例库的经验回流机制

---

*Phase 1 行动计划定稿。三个前提已确认：底座 API 现成可调、知识素材已有、样例数据可用。*
