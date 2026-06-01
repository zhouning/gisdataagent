# Standards Platform Wave 8 — `to_data_model` 派生 (P3-a)

- **状态**：Shipped (2026-06-01)
- **日期**：2026-06-01
- **作者**：周宁（@zhouning）+ Claude
- **关联 spec 总纲**：`docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`（§4.2.5、§7、to_data_model P3 占位）
- **实施 plan**：`docs/superpowers/plans/2026-06-01-std-platform-wave8-data-model.md`
- **关联 roadmap**：v25.x P3 落地为 v25.2

---

## 1. 目标

- 把派生策略 6/6 全部点亮：to_data_model 从 None 占位变为 active
- 每个 std_document_version 可派生出 CDM/LDM/PDM 三层模型 + PostgreSQL DDL
- 与既有 5 个策略对齐：支持 re-derive、stale、rollback、impact graph、manual 不被覆盖
- 前端能预览三层 JSON 与 DDL 文本（带 copy / download）

## 2. 非目标

- 反向 XMI 输出（推到 Wave 8b / v25.3）
- DDL 一键执行（危险操作）
- CDM associations / inheritance（数据源未具备）
- 手工编辑 / JSON patch 覆盖派生
- 跨版本 diff 视图

## 3. 数据模型

新增表 `std_data_model_snapshot`（migration 085）：

```sql
std_data_model_snapshot
├─ id                    UUID PK
├─ document_version_id   UUID FK -> std_document_version
├─ generated_at          timestamptz
├─ generated_by          text
├─ cdm_json              jsonb
├─ ldm_json              jsonb
├─ pdm_json              jsonb
├─ ddl_postgresql        text
├─ entity_count          int
├─ attribute_count       int
├─ constraint_count      int
├─ std_derived_link_id   UUID FK -> std_derived_link
├─ derived_status        enum('active','stale','manual')
├─ source_tag            text
└─ updated_at            timestamptz
```

migration 085 同时**放宽**两个 CHECK 约束（严格超集，不破 Wave 7）：

- `std_derived_link.source_kind` 增加 `'document_version'`
- `std_derived_link.target_kind` 增加 `'data_model'`

`link_repo._TARGET_DERIVED_STATUS_TABLES` 把 `std_data_model_snapshot` 纳入，rollback_version() 自动flip snapshot derived_status。

## 4. 派生策略

文件：`data_agent/standards_platform/derivation/strategies/data_model.py`

```
DataModelStrategy.run(version_id):
  1. SELECT std_data_element 行（仅 bound 的）
  2. SELECT 引用的 std_value_domain + std_value_domain_item
  3. SELECT 引用的 std_term
  4. data_model_renderer.build_model() → IR
     render_cdm/ldm/pdm() → 三层 JSON
     render_ddl() → PG DDL 文本
  5. INSERT std_data_model_snapshot（新行）
  6. INSERT std_derived_link
     (source_kind='document_version', target_kind='data_model')
  7. mark_stale 上一版同 doc 的 active link
     UPDATE std_data_model_snapshot SET derived_status='stale'
```

**re-derive**：每次跑都新建一行 snapshot（不 update），保留完整历史。manual snapshot 永不被动。

## 5. 渲染器（`data_model_renderer.py`）

纯函数模块（无 DB / IO）。建立 IR → 三层 JSON / DDL：

| 入参 | 出参 |
|---|---|
| `build_model(elements=, value_domains=, terms=)` | `{entities: [...], warnings: [...], stats: {...}}` |
| `render_cdm(IR)` | 概念层（实体 + 中文名 + 属性名） |
| `render_ldm(IR)` | 逻辑层（+ logical_type + nullable） |
| `render_pdm(IR)` | 物理层（+ physical_type + 约束） |
| `render_ddl(IR, dialect='postgresql')` | DDL 文本 |

**类型映射（PG）**：

| representation_class | value_domain.kind | PG 类型 | 约束 |
|---|---|---|---|
| code | enumeration | VARCHAR(64) | CHECK (col IN (…)) |
| code | pattern | VARCHAR(64) | CHECK (col ~ '…') |
| code | range | VARCHAR(64) | — |
| text | * | TEXT | — |
| integer | range | BIGINT | CHECK BETWEEN |
| integer | * | BIGINT | — |
| decimal | range | NUMERIC(18,4) | CHECK BETWEEN |
| decimal | * | NUMERIC(18,4) | — |
| datetime | * | TIMESTAMPTZ | — |
| boolean | * | BOOLEAN | — |
| geometry | * | GEOMETRY(\<type\>, \<srid\>) | + GIST 索引 |

**obligation 映射**：mandatory → NOT NULL。其余不加。

**注释**：`COMMENT ON TABLE` 用 entity name_zh，`COMMENT ON COLUMN` 用 element.name_zh。

**几何 SRID**：从 `std_data_element.unit` 解析（"POLYGON@4490" / "EPSG:4490"）；缺省 4326。

## 6. REST 端点

挂在 `data_agent/api/standards_routes.py`：

| 路径 | 方法 | 行为 | 权限 |
|---|---|---|---|
| `/api/std/data-model/{vid}` | GET | 完整 payload；可 `?layer=cdm\|ldm\|pdm\|ddl` 单层取 | 任何已登录用户 |
| `/api/std/data-model/{vid}/ddl` | GET | text/plain DDL，Content-Disposition 文件名 | 同上 |
| `/api/std/data-model/{vid}/snapshots` | GET | 历史列表（active + stale + manual） | 同上 |

写入侧仍走既有 `/api/std/derive/rerun/{vid}`（admin only），与其他 5 strategy 一致。

## 7. 前端

最小改动：

- `DeriveSubTab.tsx`：右侧增加「📐 查看数据模型 (CDM/LDM/PDM/DDL)」按钮
- `DataModelPreviewModal.tsx`：4 tab modal（PDM/DDL/LDM/CDM），DDL 带「复制」+「下载 .sql」
- `standardsApi.ts`：4 个 SDK 函数
- 不新增独立 sub-tab（待 Wave 8b 反向 XMI 一起规划）

## 8. 测试覆盖

| 文件 | 数量 | 说明 |
|---|---|---|
| `test_migration_085.py` | 8 | 表结构、索引、CHECK 放宽、cascade、与 Wave 7 兼容 |
| `test_data_model_renderer.py` | 16 | 纯函数：分组、unbound 跳过、dedup、term 解析、所有类型映射、约束、几何 SRID、DDL 关键字 |
| `test_data_model_strategy.py` | 11 | DB 集成：单/多表、enum/pattern/range CHECK、geometry+GIST、mandatory→NOT NULL、re-derive stale、manual 保留、unbound 不报错、source_kind 正确、rollback、runner 状态 |
| `test_api_data_model.py` | 11 | 4 路由：401 / 404 / 400 / happy / layer 筛选 / 历史列表 / viewer 可读 |
| **小计** | **+46** | |

迁移到 v25.1 已有 **264** 后，全套 standards_platform 测试达到 **310 passed**（+46 net new）。

未受影响但被改测试断言的 Wave 7 测试同步更新：
- `test_derivation_runner.py::test_get_strategy_status_lists_six` — 5/1 → 6/0
- `test_derive_handler.py::test_list_strategies` — 5/1 → 6/0
- `test_derivation_runner.py::test_dispatch_runs_active_strategy` — 增加 to_data_model 断言

## 9. 已知风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | code 列默认 VARCHAR(64) 长度可能截断 | 提到模块常量 `DEFAULT_CODE_LENGTH`，未来加 `std_data_element.max_length` 列即可平滑升级 |
| 2 | bound_table 命名冲突（同表多元素） | `build_model()` dedup + warning 入 IR；UI 侧未来高亮 |
| 3 | CDM name_zh 解析 fallback 丑 | humanize(table_name) 兜底；Wave 8b 引入 entity-level 命名表 |
| 4 | snapshot 表膨胀 | 保留全部历史；如有性能问题加 retention job |
| 5 | DDL 不可在已有表执行 | 文案明示"应当如何"，不是 DML 脚本 |

## 10. 验收（已通过）

- [x] `pytest data_agent/standards_platform/` 全绿（310 passed，2 pre-existing 不相关失败）
- [x] migration 085 在 Huawei DB 落地
- [x] CQ 数据集（cq_dltb 等）测试场景通过：DDL 含 CREATE TABLE / NOT NULL / CHECK / GEOMETRY / GIST / COMMENT
- [x] `cd frontend && npm run build` exit 0
- [x] `GET /api/std/derive/strategies` 返回 `to_data_model.status='active'`
- [x] roadmap.md 更新派生覆盖率 6/6 (100%)

## 11. Commit 链路

| commit | 内容 |
|---|---|
| `db2f6c2` | migration 085 + std_data_model_snapshot + CHECK 放宽 + 8 tests |
| `88cc6c6` | data_model_renderer + 16 tests |
| `5b3e6b3` | DataModelStrategy + register in runner + 11 tests |
| `8ee1d94` | /api/std/data-model/* routes + 11 tests |
| `72361d2` | DataModelPreviewModal + DeriveSubTab + 4 SDK fns + npm build |
| _本 commit_ | spec + roadmap v25.2 |
