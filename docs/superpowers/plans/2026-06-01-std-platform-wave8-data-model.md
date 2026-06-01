# Standards Platform Wave 8 — `to_data_model` 派生 (P3-a)

- **状态**：Plan（待用户审批）
- **日期**：2026-06-01
- **作者**：周宁（@zhouning）+ Claude
- **关联 spec**：`docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`（§4.2.5、§7、`to_data_model` P3 占位）
- **关联 roadmap**：v25.x P3 / 派生覆盖率 5/6 → 6/6
- **目标版本号**：v25.2

---

## 1. 目标

把 6 个派生策略中最后一个 `to_data_model` 从 `None` 占位提升为可运行实现，把单向权威派生覆盖率从 **5/6 (83%)** 推到 **6/6 (100%)**。

具体功能：

1. 一个标准的某个版本能被派生成 **CDM / LDM / PDM 三层模型**
2. PDM 层能渲染出 **PostgreSQL 方言的 DDL**（CREATE TABLE + 约束 + GIST 索引 + 注释）
3. 派生结果 + DDL 一起持久化为 snapshot，可通过 REST 取回
4. 与既有 5 个策略一样支持 re-derive、stale、rollback、impact graph
5. 前端 `DeriveSubTab` 增加 Data Model 预览（可复制 DDL）

## 2. 非目标（P3-a 范围之外）

- **反向 XMI 输出** — 单独 follow-up wave（Wave 8b / v25.3）；需要对 EA fixtures 做 round-trip 验证
- **DDL 一键执行** — 危险操作，需要 RBAC + 二次确认流；这次只暴露文本
- **CDM 关系建模（associations / inheritance）** — Wave 8b 一起做，需要新数据源（目前 std_data_element 不带关系信息）
- **手工编辑 / 覆盖派生** — 后续做 JSON patch 机制
- **跨版本 diff** — 已有 std_derived_link 链路天然支持，但 UI 单独做

## 3. 设计

### 3.1 数据存储 — 单 snapshot 表

新增一张表：`std_data_model_snapshot`

```sql
CREATE TABLE std_data_model_snapshot (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    generated_by            TEXT NOT NULL DEFAULT 'system',

    -- 派生产物
    cdm_json                JSONB NOT NULL DEFAULT '{}'::jsonb,
    ldm_json                JSONB NOT NULL DEFAULT '{}'::jsonb,
    pdm_json                JSONB NOT NULL DEFAULT '{}'::jsonb,
    ddl_postgresql          TEXT  NOT NULL DEFAULT '',

    -- 派生统计（便于 UI 一眼看清覆盖率）
    entity_count            INT NOT NULL DEFAULT 0,
    attribute_count         INT NOT NULL DEFAULT 0,
    constraint_count        INT NOT NULL DEFAULT 0,

    -- 与 std_derived_link 联动（与其他派生表对齐的 stale 字段）
    std_derived_link_id     UUID REFERENCES std_derived_link(id) ON DELETE SET NULL,
    derived_status          TEXT NOT NULL DEFAULT 'active'
                                CHECK (derived_status IN ('active','stale','manual')),
    source_tag              TEXT
);
CREATE INDEX idx_std_dm_snapshot_version ON std_data_model_snapshot(document_version_id);
```

**Migration 085** 装这张表。

为什么用 snapshot 而不是 entity/attribute 双表：

- **数据冗余几乎为零** — attribute 与 std_data_element 是 1:1 的，存第二份不带新信息
- **DDL 是真正的输出物** — 用户拿走的是 .sql 文件 + 三层模型 JSON，作为 blob 存最自然
- **未来手工覆盖留口** — 现版本只 auto-derive；下一版加 `cdm_overrides JSONB` 列做 patch
- **派生统计就地查** — 不必 GROUP BY 才能给 UI 显示「N entities, M attrs」

### 3.2 策略 `DataModelStrategy`

文件：`data_agent/standards_platform/derivation/strategies/data_model.py`

```python
class DataModelStrategy(DerivationStrategy):
    name = "to_data_model"
    description = "派生标准 data_element 到 CDM/LDM/PDM 三层模型 + PostgreSQL DDL"
    
    def run(self, *, version_id, by_user="system") -> DerivationResult:
        # 1. 读取该版本所有 bound 的 std_data_element + value_domain
        # 2. 按 bound_table 分组生成 entity 列表
        # 3. 用 representation_class + value_domain 生成 attribute typing
        # 4. 调 data_model_renderer.render_*() 出三层 JSON + DDL
        # 5. 在 std_data_model_snapshot 插入一行
        # 6. 在 std_derived_link 写一行 (target_kind='data_model', 
        #    target_table='std_data_model_snapshot', target_id=snapshot_id)
        # 7. 上一版同 doc 的 active link → mark_stale + 老 snapshot derived_status='stale'
```

**派生粒度**：一个 std_document_version 派生出 **一行 snapshot + 一条 std_derived_link**。link 的 source_kind 用 `data_element`、source_id 写一个聚合占位（看下面 §3.5）。

### 3.3 类型映射（PG 方言）

| `representation_class` | `value_domain.kind` | PG 类型 | 备注 |
|---|---|---|---|
| code | enumeration | `VARCHAR(64)` + `CHECK(col IN (...))` | 从 std_value_domain_item 取 values |
| code | pattern | `VARCHAR(64)` + `CHECK(col ~ '...')` | regex |
| code | range / null | `VARCHAR(64)` | |
| text | * | `TEXT` | |
| integer | range | `BIGINT` + `CHECK(col BETWEEN a AND b)` | |
| integer | null | `BIGINT` | |
| decimal | range | `NUMERIC(18,4)` + CHECK | |
| decimal | null | `NUMERIC(18,4)` | |
| datetime | * | `TIMESTAMPTZ` | |
| boolean | * | `BOOLEAN` | |
| geometry | * | `GEOMETRY(<type>, <srid>)` | type/srid 从 element.unit 或 std_data_element 推断；fallback `Geometry(Geometry, 4326)` |

**约束**：
- `obligation='mandatory'` → `NOT NULL`
- `obligation='conditional'` → 不加 NOT NULL（业务侧条件性）
- `obligation='optional'` → 不加 NOT NULL

**索引**：
- 所有 geometry 列加 GIST 索引：`CREATE INDEX idx_<tbl>_<col>_gist ON <tbl> USING GIST (<col>);`

**注释**：
- `name_zh` 走 `COMMENT ON COLUMN <tbl>.<col> IS '<name_zh>';`
- `definition` 不重复，留给文档

### 3.4 渲染器 `data_model_renderer.py`

文件：`data_agent/standards_platform/derivation/data_model_renderer.py`

公共接口：

```python
def build_model(*, elements, value_domains, terms) -> dict:
    """构建中间表示 (Intermediate Representation)。
    
    Returns:
        {
          "entities": [
            {
              "physical_table": "cq_dltb",
              "name_zh": "土地利用现状图斑",       # 来自 std_term 匹配，缺省=physical_table
              "name_en": "land_use_dltb",
              "code": "DLTB",
              "attributes": [
                {
                  "physical_column": "DLMC",
                  "name_zh": "地类名称",
                  "representation_class": "code",
                  "logical_type": "string",
                  "physical_type": "VARCHAR(64)",
                  "nullable": false,
                  "is_geometry": false,
                  "constraints": ["CHECK (\"DLMC\" IN ('水田','旱地',...))"],
                  "comment": "地类名称",
                  "data_element_id": "<uuid>",
                  "value_domain_code": "DLMC_ENUM",
                },
                ...
              ]
            }
          ]
        }
    """

def render_cdm(model: dict) -> dict:
    """概念层 — 实体 + 中文 + 属性名，无技术细节。"""

def render_ldm(model: dict) -> dict:
    """逻辑层 — 加 logical_type + nullable，仍无 PG 方言。"""

def render_pdm(model: dict) -> dict:
    """物理层 — 加 physical_type + 索引/约束语句。"""

def render_ddl(model: dict, *, dialect="postgresql") -> str:
    """从 PDM 拼出可执行 DDL 文本。"""
```

为什么先建 IR 再 render：未来加 MySQL/Oracle/SparkSQL 方言只换 dialect，不改 IR。

### 3.5 std_derived_link 写入

snapshot 不是单元素粒度，所以 link 行设计：

- **source_kind**: `'document_version'`（新增的 source_kind 值，需要看 std_derived_link 的 CHECK；如果有 enum 限制则放宽 migration 一并改）
- **source_id**: `version_id`（即 std_document_version.id）
- **source_version_id**: `version_id`
- **target_kind**: `'data_model'`
- **target_table**: `'std_data_model_snapshot'`
- **target_id**: snapshot.id
- **derivation_strategy**: `'to_data_model'`
- **status**: `'active'`

re-derive 时：先 mark_stale 老 link + 老 snapshot.derived_status='stale'，再插入新行（snapshot 是一行新 row 不是 update）。

`rollback_version()` 已经在 link_repo 里现成了，自动适用。

### 3.6 REST 端点（4 个）

挂在 `data_agent/api/standards_routes.py`：

| 路径 | 方法 | 行为 |
|---|---|---|
| `GET /api/std/data-model/{vid}` | GET | 返回最新 active snapshot 的 cdm/ldm/pdm/ddl + 统计；query 参 `?layer=cdm\|ldm\|pdm\|ddl` 单独取 |
| `GET /api/std/data-model/{vid}/ddl` | GET | 直接返回 DDL 文本（`Content-Type: text/plain`），便于浏览器另存 .sql |
| `GET /api/std/data-model/{vid}/snapshots` | GET | 列出该版本所有 snapshot（active + stale），便于历史对比 |
| `POST /api/std/derive/rerun/{vid}` | POST（已有） | 既有路由，把 `to_data_model` 加进 active strategies 后自动触发 |

权限：`viewer` 可读，`admin` 可触发派生（与其他 strategy 一致）。

### 3.7 前端

最小改动：

- `DeriveSubTab` 在「派生覆盖率」卡片里把 `to_data_model` 从 `coming_soon` 标记成 `active`
- 「最近一次派生结果」面板里若 `to_data_model.ok=true`，多一个「查看数据模型」按钮 → 弹出 modal：
  - tab 1: PDM JSON（语法高亮）
  - tab 2: DDL（带「复制」+「下载 .sql」按钮）
  - tab 3: CDM JSON
- 不新增独立 sub-tab（待 Wave 8b 反向 XMI 一起规划独立 「Data Model」 sub-tab）

### 3.8 测试

复用现有 conftest（`fresh_clause` fixture）：

| 文件 | 测试 |
|---|---|
| `tests/test_migration_085.py` | 表存在 + 列约束 + index |
| `tests/test_data_model_strategy.py` | 8-10 个场景：单表单元素、多表多元素、enum CHECK、pattern CHECK、range CHECK、geometry SRID、mandatory→NOT NULL、re-derive stale、manual not touched、rollback |
| `tests/test_data_model_renderer.py` | IR 构建 + render_cdm/ldm/pdm 各自结构、render_ddl 文本断言（关键片段：`CREATE TABLE`、`NOT NULL`、`CHECK`、`USING GIST`、`COMMENT ON`） |
| `tests/test_api_data_model.py` | 4 路由 happy path + 401/403/404 |

目标：**+25-30 个 test**，加到现有 264 → ~290。

### 3.9 文档

- 本 plan 文件 + 同名 spec 文件（`docs/superpowers/specs/2026-06-01-std-platform-wave8-data-model-design.md`）
- 更新 `docs/roadmap.md`：v25.1 → v25.2，把 P3 项移进 v25.2 已完成段
- 更新 README "Standards Platform" 段（如果有）

## 4. 实施顺序（commit 拆分）

| # | Commit | 内容 | 测试 |
|---|---|---|---|
| 1 | `feat(std-platform): migration 085 -- std_data_model_snapshot` | migration + test_migration_085 | +1 |
| 2 | `feat(std-platform): data_model_renderer -- IR + CDM/LDM/PDM/DDL` | renderer.py + test_data_model_renderer | +10 |
| 3 | `feat(std-platform): DataModelStrategy + register in runner` | strategy + test_data_model_strategy（含 stale/manual/rollback） | +10 |
| 4 | `feat(std-platform): /api/std/data-model/* routes` | 4 routes + test_api_data_model | +6 |
| 5 | `feat(std-platform-fe): DeriveSubTab -- Data Model preview modal` | 前端 + npm build | — |
| 6 | `docs(std-platform): Wave 8 spec/plan + roadmap v25.2` | docs | — |

预计 6 commits，~5 工作日。

## 5. 验收

- [ ] `pytest data_agent/standards_platform/` 全绿，新增 ~25-30 tests
- [ ] `python -m data_agent.migrations` 把 085 落地，回滚干净
- [ ] 用 CQ 数据集（cq_dltb 等）派生一次，DDL 文本能粘到一个空 PG 库执行通过（geometry/enum/index 都生成）
- [ ] `cd frontend && npm run build` exit 0
- [ ] `GET /api/std/derive/strategies` 显示 `to_data_model.status='active'`
- [ ] 前端 modal 展示 PDM JSON + DDL，「复制」按钮可用
- [ ] roadmap.md 显示派生覆盖率 6/6 (100%)

## 6. 已知风险与权衡

1. **type-mapping 的边界情况**：`representation_class='code'` 且无 value_domain → 用 `VARCHAR(64)` 是猜测；如果标准里 code 长度超 64 会被截。**缓解**：把 `64` 提成 `data_model_renderer.DEFAULT_CODE_LENGTH` 常量，未来从 std_data_element 加 `max_length` 列时无痛升级。
2. **bound_table 命名冲突**：同一 bound_table 出现在多个 std_data_element 但属于不同语义实体（不应该但可能发生）— 当前简单策略：合并成一个 entity，所有 attributes 放一起。**缓解**：在 metadata 里加 `_warnings: ['multiple definitions']`，UI 高亮。
3. **CDM name_zh 解析**：`std_term` 不一定有匹配项，fallback = humanize(physical_table)，结果会 ugly。**缓解**：UI 显示 fallback 来源标记。
4. **snapshot 表会膨胀**：每次 re-derive 写新行，一年下来可能上千行。**缓解**：保留全部历史，加索引；如果真有性能问题，加 retention job（`>30 天且非 active 的 stale snapshot 删除`）。
5. **DDL 不可执行的边角**：用户表里已经有数据，CREATE TABLE 会失败。**预期**：DDL 是「应当如何」的描述，不是「立即执行」的脚本；前端文案明示「请在空库或对照 ALTER TABLE 使用」。

## 7. 开放问题（不影响本 wave 的，但记录下来）

- Wave 8b 反向 XMI 的 EA 兼容版本号选择（XMI 2.1 / 2.5）
- CDM 关系建模数据源：清单文件 / std_clause 引用 / 列名启发式
- DDL 多方言（MySQL / Oracle / SparkSQL）— 看后续是否真有客户场景

## 8. 触达的文件清单（预估）

新增：
- `data_agent/migrations/085_std_data_model_snapshot.sql`
- `data_agent/standards_platform/derivation/strategies/data_model.py`
- `data_agent/standards_platform/derivation/data_model_renderer.py`
- `data_agent/standards_platform/tests/test_migration_085.py`
- `data_agent/standards_platform/tests/test_data_model_strategy.py`
- `data_agent/standards_platform/tests/test_data_model_renderer.py`
- `data_agent/standards_platform/tests/test_api_data_model.py`
- `frontend/src/components/StandardsTab/DataModelPreviewModal.tsx`
- `docs/superpowers/specs/2026-06-01-std-platform-wave8-data-model-design.md`
- `docs/superpowers/plans/2026-06-01-std-platform-wave8-data-model.md`（本文件）

修改：
- `data_agent/standards_platform/derivation/runner.py`（注册 + 描述）
- `data_agent/api/standards_routes.py`（4 routes）
- `frontend/src/components/StandardsTab/DeriveSubTab.tsx`（按钮 + modal hookup）
- `frontend/src/api/standardsApi.ts`（4 SDK 函数）
- `docs/roadmap.md`（v25.2 段）

不动：
- 既有 5 个 strategy
- link_repo（rollback/impact_graph 直接复用）
- outbox/worker（已有派生触发链路）
- review/publish（已稳定）
