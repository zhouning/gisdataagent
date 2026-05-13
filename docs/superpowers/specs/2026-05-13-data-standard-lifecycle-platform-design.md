# 数据标准全生命周期智能化管理平台 —— 架构设计

- **状态**：Draft（待用户复核）
- **日期**：2026-05-13
- **作者**：周宁（@zhouning）+ Claude
- **相关目录**：`data_agent/standards_platform/`（新建）、`data_agent/standards/`（既有解析器）
- **关联 roadmap**：v25.0「数据标准全生命周期智能化」模块

---

## 0. 目标与非目标

### 目标

在现有 GIS Data Agent 内部嵌入一个以"标准条款"为单一权威源的**数据标准全生命周期平台**，覆盖**采集 → 分析 → 起草 → 审定 → 发布 → 派生**六阶段，让：

1. 系统可收集并结构化国家/行业/企业/国际标准与互联网公开标准；
2. 专家在系统内以类似"写学术论文"的体验起草标准，带精确引用追溯；
3. 最终定稿的标准在系统内管理、维护，未来辅助生成数据模型（替代 Enterprise Architect）；
4. 标准作为单向权威源派生下游：语义层（agent_semantic_hints / value_semantics / sources.synonyms）、数据质检规则、缺陷分类法（defect_taxonomy）、以及未来的数据模型 DDL。

### 非目标（本 spec 范围之外）

- 本 spec 不覆盖"概念/逻辑/物理三层建模 + DDL 输出 + 反向 XMI"的**实施**（只占位留接口，P3 单独 spec）。
- 不做实时字符级共编（Google Docs 风格）；只做**条款级锁的并发编辑**。
- 不做跨租户 / 多租户隔离（项目当前是单租户多用户）。
- 不替代现有 KB / GraphRAG / Workflow Engine，而是复用。

---

## 1. 背景与现状

### 1.1 现有与标准相关的能力（扫描结果）

| 模块 / 路径 | 作用 | 状态 |
|---|---|---|
| `data_agent/standards/docx_extractor.py` | docx 章节抽取 | 未 commit |
| `data_agent/standards/docx_standard_provider.py` | docx 标准内容提供者 | 未 commit |
| `data_agent/standards/semantic_config_generator.py` | 标准→语义配置生成器 | 未 commit |
| `data_agent/standards/cli.py` | `gis-agent standards` CLI | 未 commit |
| `data_agent/standards/compiled_docx/`、`compiled/` | 编译产物 | 未 commit |
| `data_agent/standards/xmi_parser.py`、`xmi_compiler.py` | XMI 解析编译 | 已 commit (v24.0) |
| `data_agent/knowledge_base.py`、`knowledge_graph.py` | KB / GraphRAG / 本体 | 已 commit |
| `data_agent/semantic_layer.py` + migration 069 `semantic_hints_and_value_semantics.sql` | 语义层 | v7 P0-pre 已落 DB |
| `data_agent/toolsets/governance_tools.py`（64KB）+ migration 043 `qc_reviews.sql` | QC 与治理工具 | 已 commit |
| `data_agent/standards/defect_taxonomy.yaml`（30 编码）+ `qc_workflow_templates.yaml` | 测绘 QC 标准 | 已 commit |

### 1.2 核心缺口

- **条款级结构化存储**（目前仅 yaml 章节级）
- **条款级向量化检索**
- **互联网标准检索 + 来源保全**
- **专家起草的条款级协作与引用追溯**
- **下游派生的显式映射与 stale 检测**
- **版本化发布与回滚**

### 1.3 业界对标

- **Datablau（数语）**：DDM + DAM + DDC + AIC 产品矩阵；多产品相互集成方式；AIC「海量行业知识库 + 大模型赋能」思路。
- **Collibra / Alation**：Business Glossary → Policy → Data Quality Rule 三段式。
- **ISO 11179**：元数据注册标准（术语 / 数据元 / 值域），本 spec `std_data_element` / `std_value_domain` 直接对齐其概念。
- **DAMA-DMBOK**：第 10 章（参考数据 / 主数据）、第 11 章（数仓）、第 14 章（元数据）。

结论：数语是"多产品相互集成"；本项目是单平台场景，走**内嵌子系统**更内聚，不做 subsystem 微服务拆分。

---

## 2. 用户决策（本次 brainstorming 已确认）

| # | 决策点 | 选择 |
|---|---|---|
| 1 | spec 范围 | 整体蓝图 + 第一阶段 P0 可实施 |
| 2 | P0 范围 | 标准文档采集与条款结构化（底座） |
| 3 | 标准来源 | 国家/行业 docx/pdf + 已有 XMI + 内部企业标准/术语表 + 互联网检索 |
| 4 | 辅助专家编写 | **系统内编辑 + 出品**（非外部工具） |
| 5 | 建模能力（蓝图） | 三层模型（CDM/LDM/PDM）+ DDL + 反向 XMI |
| 6 | 下游关联 | 标准 → 下游派生（单向权威源） |
| 7 | 多人协作 | 条款级锁的并发编辑 |
| 8 | 版本粒度 | 整文档版本 + 发布快照 |
| 9 | 总体方案 | A：内嵌子系统（非 subsystem 微服务、非外接 EA） |
| 10 | 目录命名 | `standards/`（解析器） + `standards_platform/`（业务层）分开 |
| 11 | 新增角色 | 可新增 `standard_editor` / `standard_reviewer` |
| 12 | 版本历史分支 | 发布后只读，中间期不保留 draft/released 双分支 |
| 13 | ltree 扩展 | 装 ltree，保留原方案 |
| 14 | 下游表字段改动 | 4 张下游表加 `std_derived_link_id` FK 列 |
| 15 | 编辑器实现 | TipTap（不接受简陋方案） |
| 16 | 新增 Agent | `StandardsEditorAgent` 作为第 7 号 Agent |
| 17 | 导出格式 | docx + pdf + json + **xlsx 数据元清单** |
| 18 | 互联网白名单兜底 | 支持手动粘贴 + URL 快照保全 |
| 19 | Outbox 模式 | 采用 PG Outbox 模式 |
| 20 | 派生失败策略 | 单 strategy 失败不阻塞 release（乐观发布） |
| 21 | Outbox worker 位置 | 独立进程 |
| 22 | 与 Celery 关系 | 独立于 Celery（PG + asyncio），未来可迁移 |
| 23 | 白名单域名 | `std.samr.gov.cn, openstd.samr.gov.cn, ogc.org, iso.org, arxiv.org, scholar.google.com, cnki.net` |
| 24 | 测试 schema 隔离 | 共用 public + fixture 清理（与项目现有风格一致） |
| 25 | E2E 条目 | 3 条关键路径 |
| 26 | pgvector | 列入系统环境要求 |
| 27 | 未 commit 代码 | P0 第一步 commit 进 main |
| 28 | worker 入口位置 | `data_agent/standards_platform/outbox_worker.py`（子包内） |
| 29 | roadmap 同步 | spec 完成后同步更新 roadmap.md |

---

## 3. 总体架构

### 3.1 命名空间

- `data_agent/standards/`（**保留**）—— 基础设施层：docx/xmi 解析器、CLI。纯解析器，无业务、无 DB schema。
- `data_agent/standards_platform/`（**新建**）—— 业务层：生命周期编排、条款/数据元 CRUD、协作、版本、引用、派生。

### 3.2 生命周期六阶段

```
[1.采集] → [2.分析] → [3.起草] → [4.审定] → [5.发布] → [6.派生]
                                                           │
                                                           ▼
                        semantic_hints / value_semantics / synonyms
                        qc_rules / defect_taxonomy / data_model (P3)
```

每一阶段对应：一组 PG 表族（前缀 `std_`）、一组 REST endpoint（前缀 `/api/std/`）、一组 ADK Skill / Agent、一个前端 sub-tab。

### 3.3 与现有系统的边界

| 复用 | 新增 |
|---|---|
| Auth/RBAC（admin/analyst + 新增 `standard_editor`、`standard_reviewer`） | `std_*` PG 表族（16 张表） |
| Workflow Engine（用于审定流转） | `data_agent/standards_platform/` Python 包 |
| Knowledge Base（向量检索后端） | `/api/std/*` 路由集（约 35 个 endpoint） |
| Observability + Audit Log | 前端 `StandardsTab`（含 6 个 sub-tab） |
| `data_agent/standards/` 解析器 | `StandardsToolset`（暴露给 Agent 的工具集） |
| `model_gateway` / `context_manager`（v15.8） | `StandardsEditorAgent`（第 7 号 Agent） |

### 3.4 全景图

```
┌──────────────────────── Standards Platform ────────────────────────┐
│                                                                     │
│  采集 ──► 分析 ──► 起草 ──► 审定 ──► 发布 ──► 派生                  │
│                                                                     │
│  ┌─────── Outbox + Worker（独立进程） ────────┐                     │
│  │ std_outbox + 双保险（进程内 + pg_cron 可选）│                     │
│  └──────────────────────┬──────────────────────┘                    │
│                         ▼                                           │
│         ┌──────── Derivation Engine（6 strategy） ────────┐         │
│         └─────────────────────┬───────────────────────────┘         │
└───────────────────────────────┼─────────────────────────────────────┘
                                ▼
  agent_semantic_hints │ registry.value_semantics │ sources.synonyms
  qc_rules             │ defect_taxonomy          │ data_model (P3)
                                │
                                ▼
       NL2SQL / QC / Governance Pipeline / Surveying QC Agent
```

---

## 4. 数据模型

### 4.1 扩展依赖

- `postgis` ✅ 已装
- `uuid-ossp` ✅ 已装
- `vector` (pgvector 0.8.0) ✅ 已装
- `ltree` ⚠️ 需在 migration 070 中 `CREATE EXTENSION ltree`

### 4.2 核心表族（16 张）

#### 4.2.1 文档与版本

```sql
std_document
├─ id                      uuid PK
├─ doc_code                text           -- GB/T 13923-2022 或 SMP-DS-001
├─ title                   text
├─ source_type             enum('national','industry','enterprise','international','draft')
├─ source_url              text
├─ language                text
├─ status                  enum('ingested','drafting','reviewing','published','superseded','archived')
├─ current_version_id      uuid FK
├─ owner_user_id           text
├─ tags                    text[]
├─ raw_file_path           text
└─ last_error_log          jsonb

std_document_version
├─ id                      uuid PK
├─ document_id             uuid FK
├─ version_label           text           -- v1.0
├─ semver_major/minor/patch int
├─ released_at             timestamptz NULL
├─ release_notes           text
├─ supersedes_version_id   uuid NULL
├─ status                  enum('draft','review','approved','released','retired')
└─ snapshot_blob           jsonb          -- 整版只读快照
```

#### 4.2.2 条款级结构

```sql
std_clause
├─ id                      uuid PK
├─ document_id             uuid FK
├─ document_version_id     uuid FK
├─ parent_clause_id        uuid NULL
├─ ordinal_path            ltree          -- "5.2.3"
├─ heading                 text
├─ clause_no               text
├─ kind                    enum('chapter','section','clause','paragraph','definition',
│                               'requirement','example','note','figure','table')
├─ body_md                 text
├─ body_html               text           -- 渲染缓存
├─ checksum                text           -- 乐观锁
├─ lock_holder             text NULL
├─ lock_expires_at         timestamptz NULL
├─ source_origin           jsonb          -- {extractor_run_id, page, span}
└─ embedding               vector(768)    -- pgvector，与现有 KB embedding_gateway 对齐
UNIQUE (document_version_id, ordinal_path)
```

#### 4.2.3 数据元 / 术语 / 值域（ISO 11179 风格）

```sql
std_term
├─ id, document_version_id, term_code, name_zh, name_en
├─ definition, aliases text[], defined_by_clause_id FK
└─ embedding vector(768)

std_data_element
├─ id, document_version_id, code, name_zh, name_en, definition
├─ representation_class    -- code | text | integer | decimal | datetime | geometry
├─ datatype                -- varchar(8) / geometry(Polygon,4326) / ...
├─ unit, value_domain_id FK NULL, term_id FK NULL
├─ obligation              -- mandatory | conditional | optional
├─ cardinality
├─ defined_by_clause_id FK
├─ data_classification     -- 继承 v15.0 的分类体系
└─ embedding vector(768)
UNIQUE (document_version_id, code)

std_value_domain
├─ id, document_version_id, code, name
├─ kind                    -- enumeration | range | pattern | external_codelist
└─ defined_by_clause_id FK

std_value_domain_item
├─ id, value_domain_id FK, value, label_zh, label_en, ordinal
UNIQUE (value_domain_id, ordinal), UNIQUE (value_domain_id, value)
```

#### 4.2.4 引用追溯

```sql
std_reference
├─ id
├─ source_clause_id FK NULL
├─ source_data_element_id FK NULL
├─ target_kind             -- std_clause | std_document | external_url | web_snapshot | internet_search
├─ target_clause_id FK NULL
├─ target_document_id FK NULL
├─ target_url text NULL
├─ target_doi text NULL
├─ snapshot_id FK NULL     -- std_web_snapshot
├─ citation_text text      -- "GB/T 13923-2022 §5.2.3"
├─ confidence numeric
├─ verified_by text NULL
└─ verified_at timestamptz NULL

std_web_snapshot
├─ id, url, http_status, fetched_at
├─ html_path text, pdf_path text NULL, extracted_text text
└─ search_query text
```

**引用无环约束**：应用层 DFS 检测，写入前校验。

#### 4.2.5 派生关联（单向标准 → 下游源）

```sql
std_derived_link
├─ id
├─ source_kind             -- clause | data_element | value_domain | term
├─ source_id uuid
├─ source_version_id FK
├─ target_kind             -- semantic_hint | value_semantic | synonym | qc_rule
│                          -- | defect_code | data_model_attribute | table_column
├─ target_table text
├─ target_id text          -- 下游主键（多类型→text）
├─ derivation_strategy text
├─ status                  -- pending | active | stale | overridden | superseded
├─ stale_reason text NULL
└─ generated_at timestamptz

UNIQUE (target_kind, target_table, target_id, status)
  PARTIAL WHERE status='active'  -- 单 active
```

**下游表 schema 改动**（migration 075）：
- `agent_semantic_hints` + `std_derived_link_id uuid NULL FK`
- `registry.value_semantics` + `std_derived_link_id uuid NULL FK`
- `sources.synonyms` + `std_derived_link_id uuid NULL FK`
- `qc_rules` 相关表 + `std_derived_link_id uuid NULL FK`

#### 4.2.6 协作 / 审定 / 评论

```sql
std_review_round
├─ id, document_version_id FK, round_no, status (open/closed)
├─ initiated_by, deadline

std_review_comment
├─ id, round_id FK, clause_id FK, parent_comment_id NULL
├─ author, body_md
├─ resolution  -- open | accepted | rejected | duplicate

std_workflow_instance   -- 复用 workflow_engine
├─ workflow_run_id, document_version_id FK
```

#### 4.2.7 互联网检索会话

```sql
std_search_session
├─ id, document_version_id FK, clause_id FK
├─ author_user_id, messages jsonb, created_at

std_search_hit
├─ id, session_id FK, query, rank, snapshot_id FK NULL, snippet
```

#### 4.2.8 Outbox

```sql
std_outbox
├─ id uuid PK
├─ event_type              -- version_released | clause_updated | derivation_requested |
│                          --   web_snapshot_needed | invalidation_needed
├─ payload jsonb
├─ created_at
├─ processed_at NULL
├─ attempts int default 0
├─ last_error text NULL
├─ next_attempt_at timestamptz NULL       -- 指数退避调度
└─ status                  -- pending | in_flight | done | failed
```

---

## 5. 组件分解

```
data_agent/standards_platform/
├─ __init__.py
├─ models.py                    # SQLAlchemy ORM（std_* 16 张表）
├─ repository.py                # CRUD + 事务边界
├─ ingestion/
│   ├─ uploader.py
│   ├─ classifier.py            # LLM 识别 source_type/doc_code
│   ├─ web_fetcher.py           # 白名单 + SSRF 防护 + robots.txt
│   └─ extractor_runner.py      # 调度 standards/docx_extractor + xmi_parser
├─ analysis/
│   ├─ structurer.py            # 章节→clause 树 + 数据元/术语/值域抽取
│   ├─ embedder.py              # pgvector 写入
│   ├─ deduper.py               # 跨标准查重
│   └─ gap_finder.py
├─ drafting/                    # P1
│   ├─ editor_session.py        # 条款级锁
│   ├─ citation_assistant.py    # 三路检索 + 插入引用
│   ├─ consistency_checker.py
│   └─ ai_suggestor.py
├─ review/                      # P2
│   ├─ workflow.py
│   ├─ comment_threads.py
│   └─ diff.py
├─ publishing/                  # P2
│   ├─ snapshot.py
│   ├─ exporter.py              # docx / pdf / json / xlsx
│   └─ supersede.py
├─ derivation/                  # P2
│   ├─ engine.py
│   ├─ strategies/
│   │   ├─ to_semantic_hint.py
│   │   ├─ to_value_semantics.py
│   │   ├─ to_synonyms.py
│   │   ├─ to_qc_rule.py
│   │   ├─ to_defect_code.py
│   │   └─ to_data_model.py     # P3 占位
│   └─ invalidator.py
├─ outbox.py                    # 表 + ORM
├─ outbox_worker.py             # 独立进程入口
├─ tools.py                     # StandardsToolset
├─ skills/                      # 6 个 ADK Skills（P1 起）
│   ├─ standard_drafting/
│   ├─ citation_validator/
│   ├─ consistency_checker/
│   ├─ derivation_runner/
│   ├─ standards_qa/
│   └─ standards_editor_agent/
└─ api.py                       # /api/std/* 路由集
```

### 5.1 前端

```
DataPanel
 └─ "数据标准" Tab
     ├─ IngestSubTab        上传 / 抓取 / 分类（P0）
     ├─ AnalyzeSubTab       条款树 / 术语 / 数据元 / 相似条款（P0）
     ├─ DraftSubTab         TipTap 编辑器 + 右侧引用助手（P1）
     ├─ ReviewSubTab        评论流 + diff（P2）
     ├─ PublishSubTab       版本时间线 + 导出（P2）
     └─ DeriveSubTab        下游影响图 + stale 列表（P2）
```

起草子 Tab 为核心体验：左（条款树）/ 中（TipTap 编辑器）/ 右（双窗：AI 起草建议 + 引用助手），对标 Overleaf + Notion 混合形态。

### 5.2 ADK 集成

- 新增 `StandardsEditorAgent` 作为 `agent.py` 中的第 7 号 Agent，独立 pipeline"Standard Authoring Pipeline"。
- Intent Router（`intent_router.py`）增加 `standard_drafting` 意图。
- `StandardsToolset` 暴露：查条款、查数据元、查术语、相似条款检索、引用搜索、一致性校验、派生运行、快照导出等约 10 个工具方法。

---

## 6. 关键数据流

### 6.1 流程 1：采集与结构化（P0 主线）

```
专家上传 GB-T-13923.docx
  → POST /api/std/documents (multipart)
  → ingestion.uploader 写 uploads/{user_id}/standards/{uuid}.docx
  → ingestion.classifier (LLM)：source_type=national、doc_code=GB/T 13923-2022
    写 std_document (status=ingested)
  → outbox 事件 extract_requested
  → extractor_runner 异步：调 standards/docx_extractor
  → analysis.structurer：章节 yaml ⇒ std_clause 树、std_term、std_data_element、std_value_domain
  → analysis.embedder：写 pgvector
  → analysis.deduper：跨标准查重，推送"相似条款已存在"
  → std_document.status=drafting，前端 AnalyzeSubTab 可视化
```

**重入幂等**：`(document_version_id, ordinal_path)` UNIQUE，重跑 extractor 走 upsert。

**失败容忍**：classifier/structurer 任一阶段失败 → status 不前进，错误写 `last_error_log`，不阻塞其他文档。

### 6.2 流程 2：起草时引用互联网标准（P1）

```
专家在 DraftSubTab 光标定位于 clause → Ctrl+Shift+R 唤起助手
  → POST /api/std/citation/search { clause_id, query }
  → drafting.citation_assistant 三路并行：
      ① pgvector 本库 clause/term（向量 + BM25 fallback）
      ② KB GraphRAG
      ③ web_fetcher 互联网（白名单域）
  → LLM rerank → 返回候选 + 自动嵌入建议
  → 专家点"插入引用"：
      若外部 URL 且本库无快照 → web_fetcher 抓 → std_web_snapshot
      写 std_reference (confidence, verified_by, verified_at)
      编辑器插入 [[ref:<id>]]
```

**CF / 403 / 429 兜底**：`POST /api/std/web-snapshots/manual` 手动粘贴正文 + URL，系统渲染为 PDF 入 std_web_snapshot。

**置信度展示**：`confidence < 0.6` 引用 chip 黄色。

### 6.3 流程 3：条款级并发编辑锁

```
专家 A 双击 clause 进入编辑
  → POST /api/std/clauses/{id}/lock
  → 原子 UPDATE std_clause
    SET lock_holder='user_A', lock_expires_at=now()+15min
    WHERE id=? AND (lock_holder IS NULL OR lock_expires_at<now())
  → 成功 → lock_token + 心跳间隔（30s）
  → 失败 → 423 Locked + 当前持有者

每 30s 心跳：POST /api/std/clauses/{id}/heartbeat（续约）

保存：PUT /api/std/clauses/{id} 带 lock_token + If-Match: <checksum>
  → checksum 不匹配 → 409 + 三方合并界面
  → 成功 → 写入 + 新 checksum + 释放锁
```

**管理员强制破锁**：`POST /api/std/clauses/{id}/lock/break` (admin only，写 audit)。

### 6.4 流程 4：版本发布与派生（P2）

```
全部审定通过 → "发布 v2.0"
  → publishing.snapshot 校验：
     ① status=approved
     ② 所有 clause 锁释放
     ③ 所有 std_reference.verified_at NOT NULL
     ④ 失败 → 422 + 阻塞清单
  → 组装 snapshot_blob，写 std_document_version
  → 触发 PG NOTIFY 'std_version_released'，同时写 std_outbox (event_type=derivation_requested)
  → outbox worker 调 derivation.engine
  → 6 个 strategy 并行：
     to_semantic_hint / to_value_semantics / to_synonyms
     to_qc_rule / to_defect_code / to_data_model (P3 占位)
  → 每条派生记录 std_derived_link + 下游表回填 std_derived_link_id
  → derivation.invalidator 与上一版对比：
     旧派生 & 新未派生 → stale
     旧未派生 & 新派生 → 新 active
     内容变 → 新 active，旧 superseded
  → 前端 DeriveSubTab 显示影响图谱
```

**乐观发布**：单 strategy 失败不阻塞 release，失败 link 标 `status='pending'` 等人工重试。

**回滚**：30 天内 `POST /api/std/versions/{id}/rollback`。

### 6.5 流程 5：影响分析

```
GET /api/std/clauses/{id}/impact
  → derivation.engine.impact_query:
     ① clause 关联的 data_element/term/value_domain
     ② std_derived_link 中的所有派生记录
     ③ 二度影响：NL2SQL 查询模板对 hint 的使用
  → 前端编辑器徽标"⚠️ 此条款绑定 12 个下游对象"
```

---

## 7. 一致性、错误处理、安全

### 7.1 错误分层

| 类别 | 例子 | 策略 | 通知 |
|---|---|---|---|
| 可恢复瞬态 | pgvector 暂挂、LLM 超时、抓取限流 | 指数退避最多 3 次，失败降级 | 观测埋点 |
| 需人工介入 | extractor 识别失败、URL 404、派生无 strategy | 标记错误态 + `last_error_log`，不中断主流程 | 前端红色角标 + 错误抽屉 |
| 一致性违规 | 引用循环、checksum 不匹配、派生目标冲突 | 事务回滚 + audit | 前端 toast |

### 7.2 关键一致性规则（DB CHECK + 应用层双保险）

1. 条款树闭合：`parent_clause_id` 指向同 `document_version_id`
2. 引用无环：DFS 检测
3. 数据元唯一：`(document_version_id, code)`
4. 值域项有序唯一：`(value_domain_id, ordinal)` + `(value_domain_id, value)`
5. 派生目标唯一：一个下游 target 同一时刻仅一条 `active`（PARTIAL UNIQUE）
6. 发布不可逆：`released` 版本不可改 clause/term/data_element
7. 锁自愈：写操作内嵌 `lock_expires_at < now()` 清理条件

### 7.3 Outbox Pattern（跨阶段事务）

所有跨组件副作用在同事务中写 `std_outbox` + 业务表。后台 worker（独立进程）每 5s 扫 `status='pending' AND next_attempt_at<=now()`。

**重试**：`next_attempt_at = now() + (2^attempts * 30s)`，封顶 1h；`attempts ≥ 5` 标 `failed`。

**双保险**：独立进程 worker + 进程内 fallback listener（可选 pg_cron）。

**与 Celery 关系**：独立于 Celery。Redis 已在 `.env` (`REDIS_URL=redis://localhost:6379/0`)，未来 v20.0 做 Celery 时可迁移，本 spec 不强依赖 Redis。

### 7.4 互联网检索安全护栏

- **白名单**（`.env` `STANDARDS_WEB_DOMAINS_ALLOWLIST`）：`std.samr.gov.cn, openstd.samr.gov.cn, ogc.org, iso.org, arxiv.org, scholar.google.com, cnki.net`
- **CF / 403 / 429 兜底**：前端手动粘贴模式
- **robots.txt**：`urllib.robotparser`
- **速率限制**：每用户每分钟 20 次（middleware 扩规则）
- **SSRF 防护**：禁止内网 IP（10/172.16-31/192.168/127/169.254）
- **大小上限**：单页 10 MB

### 7.5 RBAC

| 角色 | 采集 | 分析 | 起草 | 审定 | 发布 | 派生 | 管理 |
|---|---|---|---|---|---|---|---|
| viewer | R | R | R | R | R | R | - |
| analyst | R | R | R | R | R | R | - |
| standard_editor | CRUD | R | CRUD（自己锁） | 评论 | 提请 | R | - |
| standard_reviewer | R | R | R | CRUD | 批准 | R | - |
| admin | ALL | ALL | ALL + 破锁 | ALL | ALL + 回滚 | ALL + 重派生 | ALL |

### 7.6 数据分类 / 脱敏

- `source_type='enterprise'` 自动 `data_classification='internal'`
- 派生时 PII 标签传播到下游 semantic_hint，继续走 NL2SQL 脱敏规则

### 7.7 审计与可观测

- 所有状态迁移写现有 `agent_audit_log`，`entity_type='std_*'`
- Prometheus：`std_documents_total{status}`、`std_outbox_pending/failed`、`std_derivation_duration_seconds`、`std_web_fetches_total{domain,status}`
- AlertEngine：`std_outbox_failed>10 for 5min` → webhook；`std_derivation_duration_seconds p95>30s` → webhook

---

## 8. 测试策略

### 8.1 单元测试（~180）

放在 `data_agent/standards_platform/tests/`。覆盖：

- `ingestion.classifier`：4 种 source_type + doc_code 变体
- `ingestion.web_fetcher`：SSRF / robots / 白名单 / 限流 / 大小上限
- `analysis.structurer`：ltree 路径、抽取、重入幂等
- `analysis.embedder`：pgvector 写入 + 降级
- `analysis.deduper`：阈值、排序稳定性
- `drafting.editor_session`：锁状态机 + 并发模拟
- `drafting.citation_assistant`：三路 rerank、插入、手动模式
- `drafting.consistency_checker`：循环引用 DFS、未定义术语、值域漂移
- `review.diff`：新增/删除/修改
- `publishing.snapshot`：前置校验、结构完整性、未释放锁拒发
- `publishing.exporter`：docx/pdf/json/xlsx 四种
- `derivation.strategies.*`：每个 strategy 独立测
- `derivation.invalidator`：active/stale/superseded 标记
- `outbox_worker`：退避、failed 转态、重入恢复

### 8.2 集成测试（~40）

- 采用**共用 public + fixture 清理**（与项目现有风格一致）
- 真实 PG 连 `flights_dataset`
- fixtures：`fake_web_fetcher`、`fake_llm`（复用 model_gateway fake provider）、`pgvector_required`（pgvector 作为系统要求，不 skip）

关键测试文件：
- `test_ingest_to_structure.py`
- `test_citation_flow.py`
- `test_concurrent_editing.py`
- `test_publish_and_derive.py`
- `test_impact_analysis.py`
- `test_outbox_recovery.py`
- `test_derivation_strategies.py`
- `test_rollback.py`
- `test_rbac.py`

### 8.3 E2E（3 条关键路径，Playwright）

- `ingest-to-publish.spec.ts`：上传 → 结构化 → 起草 → 审定 → 发布
- `citation-assistant.spec.ts`：唤起助手 → 搜索 → 插入引用 → 渲染 chip
- `impact-analysis.spec.ts`：改已发布条款 → 看下游影响面板

### 8.4 性能与压力（非 CI，`benchmarks/standards_platform/`）

- 结构化吞吐：100 份 docx 并发，p95 < 60s/份
- 并发锁争抢：50 asyncio × 10 clause，无死锁、无泄漏
- 派生链路：200 数据元全派生 < 30s
- 向量检索：10 万 clause top-k=10，p95 < 500ms

### 8.5 回归

派生写的 4 张既有表，现有测试增加反向验证：
- `test_semantic_layer.py` + 3 case
- `test_nl2sql_grounding.py` + 2 case
- `test_governance_tools.py` + 3 case

### 8.6 TDD 节奏

红 → 绿 → 重构。不 mock PG；不测 ADK 框架；不做视觉回归。

---

## 9. 阶段路线

| 阶段 | 范围 | 粒度 | 后续 spec |
|---|---|---|---|
| **P0（本 spec 实施）** | 采集 + 分析（结构化 + 向量化）+ 最小 Outbox + 16 表 + REST + 2 个 sub-tab | 可实施 | — |
| **P1** | 起草（TipTap + 引用助手 + 一致性校验）+ StandardsEditorAgent | 蓝图级 | 另起 |
| **P2** | 审定 + 发布 + 派生（6 strategy，其中 to_data_model 占位） | 蓝图级 | 另起 |
| **P3** | to_data_model：CDM/LDM/PDM 三层 + DDL + 反向 XMI | 蓝图级 | 另起 |
| **P4** | 审定流模板可视化、批量回滚、跨标准影响图谱 | 占位 | — |

P0 完成后系统即具备可用价值：专家可上传标准、系统结构化展示、基于 pgvector 相似条款查找。

---

## 10. P0 实施清单（可实施粒度）

### 10.1 后端

**第 0 步（先决）**：把 `data_agent/standards/` 下未 commit 的 `docx_extractor.py` / `docx_standard_provider.py` / `semantic_config_generator.py` / `cli.py` / `compiled_docx/` / `compiled/` 以独立 commit 提交进 main，作为解析器基础设施。

**包骨架**：
- `data_agent/standards_platform/__init__.py`
- `data_agent/standards_platform/models.py`（16 张表 ORM）
- `data_agent/standards_platform/repository.py`

**采集 + 分析**：
- `ingestion/uploader.py` / `classifier.py` / `web_fetcher.py` / `extractor_runner.py`
- `analysis/structurer.py` / `embedder.py` / `deduper.py`

**Outbox**：
- `outbox.py`
- `outbox_worker.py`（独立进程入口 `python -m data_agent.standards_platform.outbox_worker`）

**REST**：`api.py` 约 12 个 endpoint（采集 + 分析阶段）。

### 10.2 Migrations

- `070_create_extension_ltree.sql`
- `071_std_documents_and_versions.sql`
- `072_std_clauses_and_data_elements.sql`
- `073_std_references_and_web_snapshots.sql`
- `074_std_outbox.sql`
- `075_alter_downstream_tables_add_derived_link_id.sql`（agent_semantic_hints / registry.value_semantics / sources.synonyms / qc_rules FK 列）

### 10.3 前端

- `frontend/src/components/datapanel/StandardsTab.tsx`（容器）
- `frontend/src/components/datapanel/standards/IngestSubTab.tsx`
- `frontend/src/components/datapanel/standards/AnalyzeSubTab.tsx`
- `frontend/src/api/standards.ts`

### 10.4 配置

- `data_agent/.env` 增：
  ```
  STANDARDS_WEB_DOMAINS_ALLOWLIST=std.samr.gov.cn,openstd.samr.gov.cn,ogc.org,iso.org,arxiv.org,scholar.google.com,cnki.net
  STANDARDS_OUTBOX_WORKER_INTERVAL_SEC=5
  STANDARDS_OUTBOX_MAX_ATTEMPTS=5
  ```

### 10.5 测试

- 约 180 单元 + 40 集成 + 0 E2E（E2E 留 P1 编辑器上线后）。

### 10.6 部署变化

新增常驻进程：`python -m data_agent.standards_platform.outbox_worker`

- Windows 本地：`nssm` 或双终端
- 生产 K8s：单副本 Deployment `outbox-worker`（PG `SELECT ... FOR UPDATE SKIP LOCKED` 已保证多副本安全，P0 单副本足够）

### 10.7 依赖

| 依赖 | 用途 | 状态 |
|---|---|---|
| pgvector (PG 扩展) | 向量存储 | ✅ 已装 0.8.0 |
| ltree (PG 扩展) | 条款路径 | 新增（migration 070） |
| python-docx | docx 抽取 / 导出 | ✅ 已有 |
| httpx / requests | web_fetcher | ✅ 已有 |
| TipTap | 起草编辑器 | P1 加 |
| weasyprint / reportlab | PDF 导出 | P2 加 |
| openpyxl | xlsx 数据元清单 | P2 加 |
| Redis | 未来 Celery 迁移路径 | ✅ `.env` 已配 |

### 10.8 DoD（Definition of Done）

- 上传 GB/T 13923-2022 docx，10 分钟内完成结构化（条款树 + 数据元 + 术语 + 值域），AnalyzeSubTab 可视化展示
- 上传第二份相似标准，系统能识别 ≥80% 的相似条款
- Outbox worker 独立进程崩溃后重启，未处理事件不丢失
- 所有测试绿、ruff / mypy 通过、`npm run build` 通过
- 更新 `docs/roadmap.md` 加 v25.x 标准平台条目

---

## 11. 与现有系统的映射

| 现有项 | 关系 | 处置 |
|---|---|---|
| v15.7 Surveying QC `defect_taxonomy.yaml` 30 编码 | 派生目标之一 | P2 增 `to_defect_code` strategy；yaml 仍可手工维护，派生 code 进 DB |
| v15.8 Prompt Registry / Model Gateway / Context Manager | 平行能力 | 起草助手走 `model_gateway`，citation_assistant 走 `context_manager` |
| v7 P0-pre `agent_semantic_hints` / `value_semantics` / `sources.synonyms` | 派生目标 | P2 写这三张表，每行带 `std_derived_link_id`；手工旧行不动 |
| XMI 解析能力（v24.0） | 采集输入 | 作为一种 source_type |
| 未 commit 的 docx_extractor / cli | 采集输入 | P0 第 0 步 commit 进 main |
| v22 已实现的补充项 + v25-v27 智能化数据治理叙事 | 衔接 | 本 spec = v25.0 标准平台模块 |

---

## 12. 未决事项 / 未来工作

1. **P1 编辑器 TipTap 扩展细节**：条款节点的 schema、引用 chip 组件、快捷键映射 —— 留 P1 spec。
2. **P2 派生 strategy 的规则细节**：值域 → CHECK 约束语法、obligation → NotNullRule 的具体模板 —— 留 P2 spec。
3. **P3 三层建模**：CDM/LDM/PDM 编辑器、DDL 输出、反向 XMI —— 留 P3 spec。
4. **v20.0 Celery 迁移**：当 Redis 实例可用且有吞吐诉求时，把 outbox worker 迁到 Celery —— 非本 spec 范围。
5. **审定流模板可视化**：P4，依赖 workflow_engine 当前 DAG 编辑器能力外扩。

---

## 13. 参考

- Datablau（数语）产品矩阵：DDM / DAM / DDC / DDS / AIC / DDM Archy / SQLink / D3（<https://www.datablau.cn/index/lists?catname=aic_top>）
- ISO/IEC 11179 Metadata Registry
- DAMA-DMBOK 2nd Edition
- Collibra Business Glossary → Policy → DQ Rule
- DCAM（Data Management Capability Assessment Model）
- Outbox Pattern（Chris Richardson, microservices.io）
- pgvector docs（<https://github.com/pgvector/pgvector>）
- PostgreSQL ltree docs（<https://www.postgresql.org/docs/16/ltree.html>）
