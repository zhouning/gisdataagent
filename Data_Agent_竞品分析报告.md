# Data Agent 竞品分析报告

> 分析日期: 2026-02-12
> 最近更新: 2026-07-27（新增 Databricks 产品体系专项对标）
> 目标: 分析 Data Agent 市场竞争格局，识别 GIS + Data Agent 差异化定位机会
> 专项报告: [GIS Data Agent 与 Databricks 最新产品体系对比分析](docs/reports/gis-data-agent-vs-databricks-product-system-comparison-2026-07-27.md)

---

## 一、市场概览

| 指标 | 数据 |
|------|------|
| AI Agent 市场规模 (2025) | $78.4 亿 |
| AI Agent 市场预测 (2030) | $526.2 亿 (CAGR 46.3%) |
| GeoAI 市场规模 (2025) | $371.3 亿 |
| GeoAI 市场预测 (2030) | $628.8 亿 (CAGR 11.1%) |
| 垂直领域 AI Agent CAGR | 62.7% (最高增长细分) |
| 企业 AI Agent 采用率 | 35% 已广泛使用，27% 实验中 |

**关键洞察**: 垂直领域 AI Agent（如 GIS+Data Agent）是增长最快的细分市场，CAGR 达 62.7%，远超通用 Agent。这意味着 **GIS Data Agent 正处于黄金窗口期**。

---

## 二、竞争格局图谱

### 2.1 竞品分级

```
┌─────────────────────────────────────────────────────────────────┐
│                        竞争格局全景                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  【直接竞争者】 GIS + AI Agent                                   │
│  ┌───────────┐  ┌───────────┐  ┌───────────────────┐           │
│  │   CARTO   │  │   Esri    │  │ Google Earth +    │           │
│  │ Agentic   │  │ ArcGIS AI │  │ Gemini            │           │
│  │ GIS       │  │ Assistant │  │                   │           │
│  └───────────┘  └───────────┘  └───────────────────┘           │
│                                                                 │
│  【间接竞争者】 通用 Data Agent                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐         │
│  │ Julius   │ │ ChatGPT  │ │ Powerdrill│ │  Manus   │         │
│  │ AI       │ │ Advanced │ │ Bloom    │ │  AI      │         │
│  │          │ │ Data     │ │          │ │          │         │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘         │
│                                                                 │
│  【核心横向平台标杆 / 潜在底座】                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Databricks Data Intelligence Platform                    │  │
│  │ Lakeflow + Unity Catalog + Genie/Agents + Apps/Lakebase  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  【相邻竞争者】 企业 BI + AI                                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ Power BI     │ │ Tableau AI   │ │ DataRobot    │            │
│  │ Copilot      │ │              │ │              │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
│                                                                 │
│  【替代方案】                                                    │
│  ┌──────────────┐ ┌─────────────┐ ┌──────────────────┐         │
│  │ Python/R +   │ │ 传统 GIS +   │ │ 招聘数据分析师 + │         │
│  │ LLM 手动编排  │ │ 手动分析     │ │ GIS 专家        │         │
│  └──────────────┘ └─────────────┘ └──────────────────┘         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 定位矩阵

```
  GIS/空间能力强 ▲
                │
    Esri        │         ★ 你的目标定位
    ArcGIS AI   │         (GIS Data Agent)
                │
    CARTO       │
    Agentic GIS │
                │
  Google Earth  │           Databricks
  + Gemini      │           Native Spatial + Agents
                │
  ──────────────┼──────────────────────────► 数据分析 Agent 能力强
                │
    Power BI    │
    Copilot     │
                │
    Tableau AI  │    Julius AI    ChatGPT
                │                 Advanced Data
                │    Powerdrill   Manus AI
                │    Bloom
                │
  GIS/空间能力弱 │
```

**更新后的核心发现**: 强 GIS + 强 Data Agent 区域仍没有单一平台完全占据，但已经不能视为“几乎空白”。CARTO 从云原生 GIS 侧进入，Databricks 则通过原生 `GEOMETRY`/`GEOGRAPHY`、H3、Lakeflow 空间管道、Lakebase PostGIS、Genie 和 Agent Bricks 从数据与 AI 平台侧逼近。GIS Data Agent 的机会不再只是“GIS + 对话”，而是自然资源标准、专业 GIS 执行、证据约束行动、规划推演和 GWM。

---

## 三、核心竞品详细分析

### 3.1 直接竞争者

#### CARTO - Agentic GIS Platform

| 维度 | 详情 |
|------|------|
| **定位** | "The Agentic GIS Platform" — 将空间分析从专家专属变为全公司决策引擎 |
| **核心能力** | 云原生 GIS + AI Agent + 自然语言空间分析 + MCP 集成 |
| **目标客户** | 企业级 GIS 团队、零售选址、物流、城市规划 |
| **定价** | 企业级定价 (非公开)，按使用量计费，提供 14 天试用 |
| **技术栈** | 云原生 (BigQuery/Snowflake/Redshift/Databricks)，模型无关 |
| **优势** | 数据不离开客户仓库; 12,000+ 地理数据集; MCP 协议支持 |
| **劣势** | 价格高; 非通用数据分析; 需要 GIS 专家创建 Agent; 学习曲线陡峭 |
| **威胁等级** | ★★★★☆ |

#### Esri - ArcGIS AI

| 维度 | 详情 |
|------|------|
| **定位** | GIS 行业巨头 + AI 增强，"Agentic AI is a new age" |
| **核心能力** | 75+ 预训练模型 + AI Assistant + ArcPy 代码生成 + 微软 Azure OpenAI 集成 |
| **目标客户** | 政府、国防、大型企业 GIS 部门 |
| **定价** | 企业级许可 (昂贵)，$100-500/用户/月 |
| **技术栈** | 桌面端 (ArcGIS Pro) + 云端 + Microsoft 365 集成 |
| **优势** | 行业标准; 75+ 预训练模型; 最全的空间分析工具集; 强大的生态 |
| **劣势** | 笨重; 价格极高; AI Agent 能力相对初期; 非云原生架构 |
| **威胁等级** | ★★★★★ (品牌和市场占有率方面) |

#### Google Earth + Gemini

| 维度 | 详情 |
|------|------|
| **定位** | 将 Gemini AI 能力注入地球观测与 GIS |
| **核心能力** | 自然语言创建数据层 + GIS 操作 + 地理空间洞察 + 无代码环境 |
| **目标客户** | 研究机构、政府、环保组织 |
| **定价** | 部分免费 + Google Cloud 企业定价 |
| **优势** | Google 品牌; Gemini 强大; 无代码; 卫星影像数据 |
| **劣势** | 仍在试点阶段; 功能有限; 非专业 GIS 工具级别 |
| **威胁等级** | ★★★☆☆ (潜在威胁大，但短期竞争有限) |

### 3.2 核心横向平台标杆

#### Databricks - Data Intelligence Platform

| 维度 | 详情 |
|------|------|
| **定位** | 面向企业的数据、分析、AI Agent 和应用统一平台，不是完整 GIS 产品 |
| **产品体系** | Lakehouse/Databricks SQL + Lakeflow + Unity Catalog + AI/BI + Genie + Agent Bricks/Framework + Apps + Lakebase |
| **Agent 能力** | Genie One/Agents/Code、Supervisor Agent、MCP、AI Search、Model Serving、MLflow 评测监控、Unity AI Gateway |
| **空间能力** | 原生 `GEOMETRY`（GA）、`GEOGRAPHY`（Public Preview）、`ST_*`、H3、Lakeflow 空间管道、Lakebase PostGIS/PostgREST |
| **优势** | 数据工程、湖仓、批流、治理、语义、BI、AgentOps、应用运行时和企业产品成熟度形成完整闭环 |
| **边界** | 不是栅格/遥感、STAC/OGC、复杂制图、3D GIS、自然资源标准和规划推演的完整专业平台 |
| **竞争关系** | 通用 Data Platform 层是核心标杆；矢量空间分析层是实质竞争者；已有 Databricks 客户中可作为 GDA 底座 |
| **威胁等级** | ★★★★★（通用平台）；★★★★☆（矢量空间分析）；★★☆☆☆（自然资源/GWM） |

**关键判断**：旧报告只把 Databricks 视为“企业 BI + AI”相邻竞争者，且以 `Databricks Assistant` 代表其 AI 能力。2026 年这一口径已经过时。Databricks 应升级为“核心横向平台标杆/潜在底座”，详细分析见 [Databricks 专项对标报告](docs/reports/gis-data-agent-vs-databricks-product-system-comparison-2026-07-27.md)。

### 3.3 间接竞争者 (通用 Data Agent)

#### Julius AI

| 维度 | 详情 |
|------|------|
| **定位** | "AI for Data Analysis" — 专业数据分析 Agent |
| **核心能力** | 32GB 文件上传 + 多模型切换 + 可视化编辑 + 数据库连接 + Notebook |
| **目标客户** | 数据分析师、研究人员、商业用户 |
| **定价** | 免费版 + Pro $20/月 + Team $25/用户/月 |
| **优势** | 专为数据分析设计; 32GB 文件支持; 多模型; Agent 式多步推理 |
| **劣势** | **无 GIS/空间分析能力**; 文件自动删除; 学习曲线 |
| **威胁等级** | ★★★☆☆ |

#### ChatGPT Advanced Data Analysis

| 维度 | 详情 |
|------|------|
| **定位** | 通用 AI + 数据分析能力 |
| **核心能力** | 代码执行 + 数据可视化 + 文件分析 |
| **定价** | Plus $20/月，Team $25/用户/月 |
| **优势** | 用户基数最大; 品牌知名度; 通用能力强 |
| **劣势** | 50MB 文件限制; **无 GIS 能力**; 无法安装复杂包; 可能幻觉 |
| **威胁等级** | ★★☆☆☆ |

#### Powerdrill Bloom

| 维度 | 详情 |
|------|------|
| **定位** | 从脏数据清洗到演示文稿的全管道分析 |
| **核心能力** | 深度趋势分析 + PDF 清洗 + 生成演示文稿 |
| **优势** | 全流程; 深度分析 |
| **劣势** | **无 GIS 能力**; 较新产品, 生态有限 |
| **威胁等级** | ★★☆☆☆ |

---

## 四、功能对比矩阵

| 能力领域 | 你的产品 (目标) | CARTO | Esri ArcGIS | Databricks | Julius AI | ChatGPT | Power BI |
|---------|:----------:|:-----:|:-----------:|:----------:|:---------:|:-------:|:--------:|
| **空间分析** | | | | | | | |
| 地图可视化 | ★★★★ | ★★★★★ | ★★★★★ | ★★★ | ✗ | ✗ | ★★ |
| 空间查询 (缓冲区/叠加) | ★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ✗ | ✗ | ✗ |
| 地理编码/逆地理编码 | ★★★ | ★★★★ | ★★★★★ | ★★ | ✗ | ✗ | ★ |
| 路径分析/网络分析 | ★★★ | ★★★ | ★★★★★ | ★★ | ✗ | ✗ | ✗ |
| 栅格/遥感/OGC/STAC | ★★★★★ | ★★★★ | ★★★★★ | ★★ | ✗ | ✗ | ✗ |
| **数据平台与分析** | | | | | | | |
| 批流、CDC 与调度 | ★★★ | ★★ | ★★ | ★★★★★ | ✗ | ✗ | ★★ |
| 统一治理、血缘与审计 | ★★★★ | ★★★ | ★★★★ | ★★★★★ | ✗ | ✗ | ★★★ |
| 自然语言查询 | ★★★★ | ★★★ | ★★★ | ★★★★★ | ★★★★ | ★★★★★ | ★★★ |
| 多格式数据导入 | ★★★ | ★★★ | ★★★ | ★★★★★ | ★★★★★ | ★★ | ★★★★ |
| 统计分析 | ★★★ | ★★ | ★★★ | ★★★★★ | ★★★★ | ★★★ | ★★★ |
| 数据可视化/图表 | ★★★ | ★★★ | ★★★ | ★★★★ | ★★★★★ | ★★★ | ★★★★★ |
| **AI Agent 能力** | | | | | | | |
| 自主多步推理 | ★★★★ | ★★★ | ★★ | ★★★★★ | ★★★★ | ★★★ | ★★ |
| 空间推理 | ★★★★ | ★★★★ | ★★★ | ★★★ | ✗ | ★ | ✗ |
| 代码生成与执行 | ★★★ | ★★ | ★★★ | ★★★★★ | ★★★★ | ★★★★ | ★★ |
| 工具调用/MCP 集成 | ★★★★ | ★★★★ | ★★★ | ★★★★★ | ★★ | ★★★ | ★★ |
| Agent 评测、网关与监控 | ★★★★ | ★★ | ★★ | ★★★★★ | ★ | ★★ | ★★ |
| **产品体验** | | | | | | | |
| 上手难度 (低=好) | ★★★★ | ★★ | ★ | ★★ | ★★★★ | ★★★★★ | ★★★ |
| 中文支持 | ★★★★★ | ★★ | ★★ | ★★★ | ★★★ | ★★★★ | ★★★★ |
| 价格亲民度 | ★★★★ | ★ | ★ | ★ | ★★★★ | ★★★★ | ★★★ |

> ★★★★★=最强 ★★★★=强 ★★★=够用 ★★=弱 ★=很弱 ✗=未发现一等产品能力。该矩阵是战略判断，不替代实测 benchmark；“你的产品”列为目标能力，当前实现与目标状态见专项报告。

---

## 五、定位分析

### 5.1 各竞品定位声明

| 竞品 | 定位声明 |
|------|---------|
| **CARTO** | "For GIS teams who need to scale spatial intelligence, CARTO is an agentic GIS platform that democratizes location analytics. Unlike Esri, CARTO is cloud-native and AI-first." |
| **Esri** | "For organizations needing comprehensive geospatial solutions, ArcGIS is the industry-standard GIS platform with AI. Unlike startups, Esri offers 50+ years of trust and the deepest toolset." |
| **Databricks** | 通用 Data Intelligence Platform，统一数据工程、湖仓、治理、BI、Agent、应用和事务数据库；不是完整 GIS，但已具备原生空间数据工程能力。 |
| **Julius AI** | "For analysts who need to turn data into insights, Julius is a purpose-built AI data analyst. Unlike ChatGPT, Julius handles 32GB files with multi-model flexibility." |
| **ChatGPT** | "For everyone who needs AI assistance, ChatGPT is the most versatile AI. Unlike specialized tools, ChatGPT does everything." |

### 5.2 可防守的定位机会

```
┌─────────────────────────────────────────────────────┐
│              差异化定位地图                           │
│                                                     │
│  ❌ 拥挤定位: "通用 AI 助手" (ChatGPT, Copilot...)   │
│  ❌ 拥挤定位: "企业 GIS 平台" (Esri, CARTO)          │
│  ❌ 拥挤定位: "数据分析工具" (Julius, Powerdrill)     │
│  ❌ 高风险定位: "通用 Data + AI 平台" (Databricks)    │
│                                                     │
│  ✅ 用户定位: "非 GIS 专家的可信空间洞察 Agent"       │
│  ✅ 产品定位: "受治理的地理空间决策与行动层"          │
│  ✅ 技术定位: "专业 GIS + Evidence + GWM"             │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 5.3 建议定位

> **For** 需要从空间数据中获取洞察的业务决策者和数据分析师，
> **who** 不具备专业 GIS 技能但需要空间分析能力，
> **[Product]** 是一个 **GIS Data Agent（空间数据智能体）**，
> **that** 通过自然语言对话自动完成空间数据分析、可视化和洞察。
> **Unlike** CARTO/Esri 需要专业 GIS 知识，或 Julius/ChatGPT 缺乏空间分析能力，
> **[Product]** **让每个人都能用自然语言完成专业级的空间数据分析**。

面向企业架构和平台采购，不建议使用“GIS 版 Databricks”或“替代 Databricks”作为定位。推荐表述为：

> **Databricks-compatible 的受治理地理空间决策与行动层。**

对于已经采用 Databricks 的客户，GIS Data Agent 可作为 Databricks App、MCP/Agent、GIS 服务控制层和自然资源领域包；对于私有化、国产化和数据主权场景，则保留开放湖仓、PostGIS、STAC/OGC 和可替换 provider 主线。

---

## 六、市场趋势与战略影响

### 6.1 关键趋势

| 趋势 | 驱动因素 | 时间线 | 对我们的影响 | 竞品动向 |
|------|---------|--------|------------|---------|
| **Agentic GIS 兴起** | AI 技术成熟 + 空间分析民主化需求 | 正在发生 | 验证了 GIS+Agent 赛道 | CARTO 已率先定义品类 |
| **MCP 协议标准化** | Anthropic 推动 + 企业集成需求 | 正在发生 | 应支持 MCP 以融入生态 | CARTO 已支持 MCP |
| **多 Agent 协作** | 复杂任务需求 | 正在发生 | 空间 Agent 可作为专家 Agent 被编排 | Databricks Supervisor 已编排 Genie、MCP 和 custom agents |
| **空间能力进入 Lakehouse** | 原生空间类型、H3、空间流处理 | 正在发生 | 仅有 PostGIS/GIS 算子不再构成充分壁垒 | Databricks Geometry/H3/Lakeflow/Lakebase PostGIS |
| **空间数据民主化** | 非 GIS 用户增长 | 正在发生 | 核心机会 — 降低门槛 | Esri/CARTO 开始但做得不够 |
| **实时空间 AI** | IoT + 边缘计算 | 1-3 年 | 差异化方向 | Esri ArcGIS 2026 |
| **中国市场空白** | 国产化需求 + 数据安全 | 正在发生 | 巨大机会 — 无直接竞品 | 国外产品未深入中国市场 |

### 6.2 战略响应建议

| 趋势 | 响应策略 | 说明 |
|------|---------|------|
| Agentic GIS | **Lead（领先）** | 在中国市场率先定义 "GIS Data Agent" 品类 |
| MCP 协议 | **Fast Follow（快速跟进）** | 支持 MCP，让产品可被 Claude/其他 Agent 调用 |
| 多 Agent 协作 | **Build Selectively（选择性建设）** | 聚焦 GIS Specialist、权限、证据和行动边界，不复制通用 Supervisor |
| Databricks 兼容 | **Integrate（集成）** | 建设 SQL/Unity Catalog/OpenSharing/Apps/MCP/Lakebase provider 与互操作 benchmark |
| 通用 Data Platform | **Avoid Head-on（避免正面竞争）** | 通用接入、湖仓、BI 和模型托管优先复用成熟 provider |
| 空间数据民主化 | **Lead（领先）** | 这是核心价值主张，用自然语言消除 GIS 门槛 |
| 中国市场 | **Lead（领先）** | 国产化 + 中文优先是独有优势 |

---

## 七、你的差异化优势分析

### 7.1 独有竞争壁垒

```
┌────────────────────────────────────────────┐
│            护城河分析                        │
│                                            │
│  1. GIS 核心能力                            │
│     ├── 空间数据处理经验                    │
│     ├── 地理分析算法积累                    │
│     └── 行业 Know-how                      │
│                                            │
│  2. Data Agent + GIS 交叉能力               │
│     ├── 自然语言 → 空间分析                 │
│     ├── 自动地图可视化                      │
│     └── 空间推理（LLM + GIS 工具）          │
│                                            │
│  3. 本土化优势 (如面向中国市场)              │
│     ├── 中文空间数据理解                    │
│     ├── 国产地图服务集成                    │
│     └── 合规 (数据不出境)                   │
│                                            │
└────────────────────────────────────────────┘
```

### 7.2 SWOT 总结

| | 有利 | 不利 |
|--|------|------|
| **内部** | **Strengths** | **Weaknesses** |
| | GIS 核心技术能力 | 品牌知名度低 |
| | 空间数据理解深入 | Agent/LLM 能力需建设 |
| | 本土化/中文优势 | 产品从 0 到 1 |
| | 交叉领域先发 | 团队规模有限 |
| **外部** | **Opportunities** | **Threats** |
| | 尚无单一平台覆盖完整 GIS + Agent + Evidence + GWM | CARTO 快速迭代 |
| | 垂直 Agent CAGR 62.7% | Esri+Microsoft 联盟 |
| | 中国市场无直接竞品 | Google Earth+Gemini 潜力 |
| | 空间数据民主化趋势 | Databricks 原生空间、PostGIS、Apps 与 Agents 组合下沉 |
| | Databricks-compatible 领域层机会 | 通用 Agent/Data Platform 可能吸收基础 GIS 能力 |

---

## 八、产品策略建议

### 8.1 MVP 功能优先级

| 优先级 | 功能 | 理由 |
|:------:|------|------|
| P0 | 自然语言 → 地图可视化 | 核心价值，秒级体验 "Wow" 时刻 |
| P0 | GeoJSON/CSV/Excel 数据上传 + 空间分析 | 覆盖最常见使用场景 |
| P0 | 多轮对话式空间数据探索 | Agent 核心交互模式 |
| P1 | 缓冲区/热力图/聚类等常用 GIS 分析 | 差异化于通用 Data Agent |
| P1 | 图表 + 地图组合报告生成 | 数据分析产出物 |
| P1 | 中文空间语义理解 | 本土化壁垒 |
| P2 | 数据库/数据仓库连接 | 企业级场景 |
| P2 | MCP 工具协议支持 | 生态集成 |
| P2 | 多 Agent 协作 (空间 Agent + 统计 Agent) | 复杂分析场景 |

### 8.2 Go-to-Market 建议

1. **品类创建**: 率先在市场上定义 "GIS Data Agent / 空间数据智能体" 品类
2. **场景切入**: 从高频刚需场景入手 — 选址分析、区域销售分析、城市规划辅助
3. **定价策略**: 采用 Freemium 模式，免费版吸引用户，Pro 版 ¥99-199/月
4. **差异化信息**: "不懂 GIS 也能做专业空间分析" — 强调降低门槛而非功能多

---

## 九、竞争监测清单

持续跟踪以下信号:

- [ ] CARTO 产品更新 (blog.carto.com) — 每月
- [ ] Esri ArcGIS AI 功能发布 (esri.com/arcnews) — 每季度
- [ ] Google Earth + Gemini 进展 — 每季度
- [ ] Databricks Genie/Agent Bricks/Unity AI Gateway 更新 — 每月
- [ ] Databricks Geometry/Geography/H3/Lakebase PostGIS 更新 — 每月
- [ ] Julius AI 功能更新 — 每月
- [ ] 国内竞品出现 (关注超图、中地数码的 AI 动向) — 持续
- [ ] AI Agent 开源框架发展 (LangChain, CrewAI) — 每月

---

## 来源

- [CB Insights - AI Agent Market Map](https://www.cbinsights.com/research/ai-agent-market-map-2025/)
- [MarketsandMarkets - AI Agents Market](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html)
- [Google Cloud - AI Agent Trends 2026](https://cloud.google.com/resources/content/ai-agent-trends-2026)
- [CARTO - Agentic GIS Platform](https://carto.com)
- [CARTO - Agentic GIS Blog](https://carto.com/blog/agentic-gis-bringing-ai-driven-spatial-analysis-to-everyone)
- [Esri - Geospatial AI](https://www.esri.com/en-us/geospatial-artificial-intelligence/overview)
- [Zerve - AI Data Analysis Tools](https://www.zerve.ai/blog/ai-data-analysis-tools)
- [8allocate - AI Agents for Data Analysis Guide](https://8allocate.com/blog/what-are-ai-agents-for-data-analysis/)
- [OvalEdge - Agentic Analytics Tools](https://www.ovaledge.com/blog/agentic-analytics-tools/)
- [Julius AI vs ChatGPT](https://julius.ai/compare/julius-vs-chatgpt)
- [Straive - Top Agentic AI Companies 2026](https://www.straive.com/blogs/top-agentic-ai-companies-2026/)
- [GeoAI AAG 2026](https://giscience.psu.edu/2026/02/04/autonomousgis_2026aag/)
- [Geospatial Intelligence Market](https://www.marketsandmarkets.com/PressReleases/geospatial-intelligence.asp)
- [Databricks Platform](https://www.databricks.com/product/platform)
- [Databricks Lakeflow](https://www.databricks.com/product/data-engineering)
- [Databricks Artificial Intelligence](https://www.databricks.com/product/artificial-intelligence)
- [Databricks Unity Catalog](https://docs.databricks.com/aws/en/data-governance/unity-catalog/)
- [Databricks Genie](https://docs.databricks.com/aws/en/genie/)
- [Databricks Apps](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/)
- [Databricks Lakebase](https://www.databricks.com/product/lakebase)
- [Databricks ST geospatial functions](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-st-geospatial-functions)
- [Databricks Lakeflow spatial pipeline tutorial](https://docs.databricks.com/aws/en/ldp/tutorial-spatial-pipelines)
- [Databricks 专项对标报告](docs/reports/gis-data-agent-vs-databricks-product-system-comparison-2026-07-27.md)
