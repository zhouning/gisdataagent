# Standards Platform Wave 5 — Publish + to_semantic_hint Derivation Design

- **状态**：Draft（待用户复核）
- **日期**：2026-05-18
- **作者**：周宁（@zhouning）+ Claude
- **关联父 spec**：`docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md` §4.2.5 / §6.4 / §9 P2 阶段
- **关联 wave**：紧接 Wave 4「审定」(`docs/superpowers/specs/2026-05-17-std-platform-wave4-review-subtab-design.md`)

## 0. 背景与目标

### 0.1 背景

经 Wave 1-4 实施，标准平台已端到端跑通「采集 → 分析 → 起草 → 审定」四阶段：
- 专家可上传 docx 标准、做条款级结构化编辑
- 走完文档级审定 round + 引用级 audit 后，version.status 进入 `approved`

但父 spec 反复强调的核心卖点 —— **「标准作为单向权威源派生整个下游（语义层 / 质检规则 / 缺陷分类 / 数据模型）」** 还没落地。`approved` 后没有正式的「发布」机制把版本冻结，更无从谈派生到下游。

### 0.2 目标

Wave 5 完成 **P2 阶段的「发布」+ 第一个派生 strategy（to_semantic_hint）端到端**：

1. **发布机制**：`approved → released` 状态机 + 物理表仅读守卫 + 手动 fork 新版本工作流
2. **派生触发**：发布事务里 enqueue 异步 outbox 事件，独立 worker 跑派生
3. **第一个 strategy**：`to_semantic_hint` —— 标准里 bound 到物理列的 `std_data_element` 派生到 `agent_semantic_hints` 表
4. **柔性 stale**：重派生时旧 version 的 link 标 `stale`，不删
5. **与手工 hint 共存**：派生只管自己写入的行（`std_derived_link_id IS NOT NULL`），手工行（NULL）不动
6. **前端**：`PublishSubTab` + `DeriveSubTab` 两个 sub-tab 同时启用

### 0.3 非目标

- 不做发布回滚 / redact（Wave 6+）
- 不做完整的派生 audit 表 / 撤销历史
- 不做剩余 5 个 strategy（to_synonym / to_value_semantics / to_qc_rule / to_defect_code / to_data_model）—— UI 占位 coming_soon
- 不做版本树可视化、跨版本 diff
- 不做发布快照 JSONB（spec §4.2 提的 `snapshot_blob` 字段不用，靠物理表 + 守卫）
- 不做派生性能压测（Wave 5 仅 1 个 strategy，量小）

## 1. 用户决策（本次 brainstorming 已确认）

| # | 决策点 | 选择 |
|---|---|---|
| 1 | Wave 5 范围 | 发布 + to_semantic_hint 派生一起端到端 |
| 2 | 版本管理粒度 | 手动开新版本（admin fork） |
| 3 | Snapshot 形态 | 物理表仅读守卫（不写 snapshot_blob） |
| 4 | 派生触发方式 | 异步 outbox（复用 Wave 1 现成 worker） |
| 5 | 绑定关系 | std_data_element 加 bound_source_id / bound_table / bound_column 三列 |
| 6 | Stale 处理 | 柔性：旧 link / hint 标 stale，不删 |
| 7 | 与手工 hint 共存 | 独立共存（link_id IS NULL 的行不动） |
| 8 | 前端 | publish + derive 两个 sub-tab 都开 |
| 9 | RBAC | admin 独发布 |
| 10 | 回滚 | Wave 5 不做 |
| 11 | 代码组织 | 新建 publishing/ + derivation/ 两个独立包 |

## 2. 架构

### 2.1 模块边界

```
data_agent/standards_platform/
├── publishing/                                # NEW
│   ├── __init__.py
│   ├── publish_repo.py    # 状态机 + fork
│   ├── guards.py          # released 守卫 + 合并的 _block_if_not_drafting
│   └── handlers.py        # 4 endpoint
│
├── derivation/                                # NEW
│   ├── __init__.py
│   ├── strategy_base.py   # ABC: DerivationStrategy + DerivationResult
│   ├── strategies/
│   │   ├── __init__.py
│   │   └── semantic_hint.py
│   ├── link_repo.py       # std_derived_link CRUD
│   ├── runner.py          # registry + dispatch (给 outbox + handler 调)
│   └── handlers.py        # 4 endpoint
│
├── outbox/                                    # 已有
│   └── handlers.py        # 增 release_published handler 注册
│
├── review/    # Wave 4
├── drafting/  # Wave 1-3
├── analysis/  # P0
└── ingestion/ # P0
```

### 2.2 关键接口契约

```python
# publishing/publish_repo.py
publish_version(*, version_id, by_user) -> dict
  # 事务: status approved->released + insert std_publish_event + outbox enqueue
  # raises ValueError (status mismatch / already released) / LookupError

fork_version(*, source_version_id, new_label, by_user) -> str
  # 事务: 复制整个子图 + 重映射 FK + 创建 draft 版本
  # raises ValueError (source not released / label exists) / LookupError

list_published_versions(*, document_id=None) -> list[dict]
get_publish_timeline(*, version_id) -> list[dict]


# derivation/runner.py
dispatch(*, version_id, by_user='system', strategies=None) -> dict
  # 跑所有(或指定)注册 strategy, 单 strategy 失败不阻塞其他
  # 返回 {strategy_name: {ok, new, staled, failed} | {ok: false, error}}


# derivation/strategy_base.py
class DerivationStrategy(ABC):
    name: str
    def run(self, *, version_id, by_user) -> DerivationResult: ...

@dataclass
class DerivationResult:
    strategy: str
    new_links: list[DerivationLink]
    staled_links: list[str]   # link_ids
    failed: list[tuple[str, str]]
```

## 3. 数据模型

### 3.1 修改既有表

**`std_data_element`** 加 binding 三列：

```sql
ALTER TABLE std_data_element
  ADD COLUMN bound_source_id   UUID REFERENCES sources(id),
  ADD COLUMN bound_table       TEXT,
  ADD COLUMN bound_column      TEXT;

ALTER TABLE std_data_element
  ADD CONSTRAINT std_data_element_binding_consistency_check
    CHECK ((bound_source_id IS NULL AND bound_table IS NULL AND bound_column IS NULL)
        OR (bound_source_id IS NOT NULL AND bound_table IS NOT NULL AND bound_column IS NOT NULL));
```

**`agent_semantic_hints`** 加 3 列：

```sql
ALTER TABLE agent_semantic_hints
  ADD COLUMN std_derived_link_id  UUID,
  ADD COLUMN std_version_id       UUID,
  ADD COLUMN derived_status       TEXT;

ALTER TABLE agent_semantic_hints
  ADD CONSTRAINT agent_semantic_hints_derived_status_check
    CHECK (derived_status IS NULL OR derived_status IN ('active','stale'));

CREATE INDEX idx_agent_semantic_hints_derived_status
  ON agent_semantic_hints(std_version_id, derived_status)
  WHERE std_derived_link_id IS NOT NULL;
```

> `std_derived_link_id IS NULL` = 手工行；`IS NOT NULL` = 派生行。两者独立共存。

### 3.2 新建表

**`std_derived_link`**（spec §4.2.5 规划）：

```sql
CREATE TABLE std_derived_link (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_version_id UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
  source_kind         TEXT NOT NULL,    -- Wave 5: 'data_element'
  source_id           UUID NOT NULL,    -- → std_data_element.id
  strategy            TEXT NOT NULL,    -- Wave 5: 'to_semantic_hint'
  target_kind         TEXT NOT NULL,    -- Wave 5: 'agent_semantic_hint'
  target_id           TEXT NOT NULL,    -- 下游 PK (UUID 或字符串)
  status              TEXT NOT NULL DEFAULT 'active',
  derived_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  derived_by          TEXT,
  notes               JSONB,
  CONSTRAINT std_derived_link_status_check
    CHECK (status IN ('active','stale','failed'))
);

-- PARTIAL UNIQUE: 同 (strategy, target) 同时只一条 active
CREATE UNIQUE INDEX idx_std_derived_link_unique_active
  ON std_derived_link(strategy, target_kind, target_id)
  WHERE status = 'active';

CREATE INDEX idx_std_derived_link_version
  ON std_derived_link(document_version_id, strategy, status);
```

**`std_publish_event`**（轻量发布事件流）：

```sql
CREATE TABLE std_publish_event (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_version_id UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
  event_type          TEXT NOT NULL,
  actor_user_id       TEXT NOT NULL,
  occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes               TEXT,
  CONSTRAINT std_publish_event_type_check
    CHECK (event_type IN ('published','forked'))
);

CREATE INDEX idx_std_publish_event_version
  ON std_publish_event(document_version_id);
```

### 3.3 复用既有

- **outbox**：`agent_outbox` 表 + worker 已有，Wave 5 仅加一个 event_type handler 注册
- **`std_document_version.status`**：CHECK 已含 `released`（migration 071 第 46 行），不改
- **fork 复制范围**：std_clause / std_data_element / std_term / std_value_domain / std_reference 全部按 source_version_id → new_version_id 复制行；FK 在事务内重映射

### 3.4 Migration 文件

| 文件 | 内容 |
|---|---|
| `079_std_publish_derivation.sql` | std_data_element binding 列 + std_publish_event + std_derived_link |
| `080_agent_semantic_hints_derived_columns.sql` | agent_semantic_hints 3 新列 + 部分索引 |

## 4. 组件分解

### 4.1 publishing 包

**`publish_repo.py`** —— 4 个函数：

```python
publish_version(*, version_id, by_user) -> dict
fork_version(*, source_version_id, new_label, by_user) -> str
list_published_versions(*, document_id=None) -> list[dict]
get_publish_timeline(*, version_id) -> list[dict]
```

`publish_version` 关键逻辑：
1. SELECT FOR UPDATE std_document_version row (防并发双发)
2. 检查 status == 'approved'，否则 raise ValueError("status must be approved", status_code_hint=409)
3. UPDATE status='released', updated_by=by_user
4. INSERT std_publish_event (event_type='published')
5. agent_outbox enqueue (event_type='release_published', payload={'version_id': version_id})
6. 返回 {version_id, status, released_at, outbox_event_id}

`fork_version` 关键逻辑：
1. 检查 source.status == 'released'
2. 检查 (document_id, new_label) UNIQUE
3. 事务内：
   - INSERT std_document_version (status='draft', supersedes_version_id=source_version_id, semver 解析自 new_label)
   - CREATE TEMP TABLE clause_id_map (old_id, new_id)
   - INSERT std_clause + 填 map
   - INSERT std_data_element (注意保留 binding 三列，complete copy)
   - INSERT std_term / std_value_domain
   - INSERT std_reference (FK 重映射规则见下)
   - INSERT std_publish_event (event_type='forked')
4. 返回 new_version_id

**std_reference FK 重映射规则**（fork 时）：
- `source_clause_id` —— 永远是本 doc 内的，必经 clause_id_map 重映射到新 clause id
- `target_clause_id` —— 当 reference 指向**本 doc 同一 version** 内的 clause（即 old_id 出现在 map 里）→ 走 map 重映射；当指向**别的 doc** → 保留原 id 不动
- `target_data_element_id` / `target_term_id` —— Wave 5 范围内不重映射（这两类 reference 量小且通常跨 doc）；如有需要 Wave 6 加映射表
- `target_url` —— 不动

**`guards.py`**：

```python
def is_version_released(version_id) -> bool

def block_if_released(version_id) -> JSONResponse | None
    # 用于 publish handler 内部检查

def block_if_not_drafting(version_id) -> JSONResponse | None
    # Wave 4 _block_if_reviewing 的扩展替代品
    # status='draft'      → None (放行)
    # status='review'     → 409 "version under review, drafting blocked"
    # status='approved'   → 409 "version status 'approved', drafting blocked"
    # status='released'   → 409 "version released, immutable"
    # status='retired'    → 409 "version status 'retired', drafting blocked"
```

**`handlers.py`** —— 4 endpoints（详见 §5）。

### 4.2 derivation 包

**`strategy_base.py`** —— ABC + dataclass：

```python
@dataclass
class DerivationLink:
    source_kind: str
    source_id: str
    target_kind: str
    target_id: str
    notes: dict | None = None

@dataclass
class DerivationResult:
    strategy: str
    new_links: list[DerivationLink]
    staled_links: list[str]
    failed: list[tuple[str, str]] = field(default_factory=list)


class DerivationStrategy(ABC):
    name: str

    @abstractmethod
    def run(self, *, version_id: str, by_user: str) -> DerivationResult: ...
```

**`strategies/semantic_hint.py`** —— 核心派生：

伪码：
```python
class SemanticHintStrategy(DerivationStrategy):
    name = "to_semantic_hint"

    def run(self, *, version_id, by_user):
        # 1. 读 bound data_element
        elements = SELECT * FROM std_data_element
                    WHERE document_version_id = version_id
                      AND bound_source_id IS NOT NULL

        # 2. 找 doc 的 prev_active_links
        doc_id = SELECT document_id FROM std_document_version WHERE id = version_id
        prev_active = SELECT * FROM std_derived_link
                       WHERE strategy = 'to_semantic_hint' AND status = 'active'
                         AND document_version_id IN
                             (SELECT id FROM std_document_version WHERE document_id = doc_id)

        # 3. 跑 upsert
        new_links = []
        failed = []
        with transaction:
            for el in elements:
                try:
                    target_id = upsert_hint(el, version_id, by_user)
                    link_id = link_repo.create_link(
                        version_id=version_id,
                        source_kind='data_element', source_id=el.id,
                        strategy=self.name,
                        target_kind='agent_semantic_hint', target_id=target_id,
                        by_user=by_user)
                    new_links.append(DerivationLink(...))
                except Exception as e:
                    failed.append((el.id, str(e)))

            # 4. mark stale
            new_target_ids = {l.target_id for l in new_links}
            staled = []
            for link in prev_active:
                if link.target_id not in new_target_ids:
                    UPDATE std_derived_link SET status='stale' WHERE id = link.id
                    UPDATE agent_semantic_hints SET derived_status='stale'
                      WHERE std_derived_link_id = link.id
                    staled.append(link.id)

        return DerivationResult(strategy=self.name, new_links=new_links,
                                staled_links=staled, failed=failed)


    def upsert_hint(self, el, version_id, by_user):
        # 查同 (source_id, table_name, column_name) 的 hint
        existing = SELECT * FROM agent_semantic_hints
                    WHERE source_id = el.bound_source_id
                      AND table_name = el.bound_table
                      AND column_name = el.bound_column

        # 三种情况：
        # (a) existing 无: INSERT 新行
        # (b) existing 有 + std_derived_link_id IS NOT NULL: UPDATE 派生字段 + 翻 stale 行的 active
        # (c) existing 有 + std_derived_link_id IS NULL: SKIP (手工行不动)
        ...
        return target_id_of_hint_row
```

字段映射（写入 agent_semantic_hints）：

| std_data_element | agent_semantic_hints |
|---|---|
| `bound_source_id` | `source_id` |
| `bound_table` | `table_name` |
| `bound_column` | `column_name` |
| `name_zh` | `description` |
| `datatype` | `data_type` |
| `obligation == 'mandatory'` | `nullable = false` |
| value_domain（如有）展开为 enum / range | `value_constraint` (JSONB) |

**`link_repo.py`**：

```python
create_link(*, version_id, source_kind, source_id, strategy, target_kind, target_id, by_user, notes=None) -> str
list_links_by_version(*, version_id, strategy=None, status=None) -> list[dict]
list_active_links_for_doc(*, document_id, strategy) -> list[dict]
mark_stale(*, link_ids: list[str]) -> int
get_link(link_id) -> dict | None
```

**`runner.py`** —— registry + dispatch：

```python
_REGISTRY: dict[str, DerivationStrategy | None] = {
    'to_semantic_hint': SemanticHintStrategy(),
    'to_synonym': None,            # Wave 6+
    'to_value_semantics': None,
    'to_qc_rule': None,
    'to_defect_code': None,
    'to_data_model': None,
}

def get_strategy_status() -> list[dict]:
    """返回 [{name, status: 'active'|'coming_soon', description}]"""

def dispatch(*, version_id, by_user='system', strategies=None) -> dict:
    """跑所有 active strategy。单 strategy try/except 隔离。"""
    results = {}
    active = {n: s for n, s in _REGISTRY.items() if s is not None}
    if strategies:
        active = {n: s for n, s in active.items() if n in strategies}
    for name, strategy in active.items():
        try:
            r = strategy.run(version_id=version_id, by_user=by_user)
            results[name] = {'ok': True, 'new': len(r.new_links),
                             'staled': len(r.staled_links),
                             'failed': len(r.failed),
                             'failures': r.failed[:10]}  # 前 10 条详情
        except Exception as e:
            results[name] = {'ok': False, 'error': str(e)}
    return results
```

**`handlers.py`** —— 4 endpoints（详见 §5）。

### 4.3 outbox 增量

`outbox/handlers.py` 添加：

```python
def handle_release_published(payload: dict) -> dict:
    version_id = payload['version_id']
    return derivation.runner.dispatch(version_id=version_id)
```

注册到 dispatcher 的 event_type 路由：

```python
EVENT_HANDLERS = {
    # ...已有的
    'release_published': handle_release_published,
}
```

### 4.4 路由注册

`api/standards_routes.py` 增 8 个 Route + 守卫合并改造：
- `_block_if_reviewing` 替换为 `_block_if_not_drafting`（在 publishing/guards.py，handler 端 import）
- 给 lock_clause / save_clause_route / citation_insert / break_clause_lock 都过这个守卫

## 5. REST API 全集

### 5.1 Publishing

| Method | Path | Auth | Body / Query | Response | Errors |
|---|---|---|---|---|---|
| POST | `/api/std/publish/versions/{version_id}` | admin | `{}` | 201 `{version_id, status, released_at, outbox_event_id}` | 404 / 409 status_not_approved / 409 already_released |
| POST | `/api/std/publish/fork` | admin | `{source_version_id, new_label}` | 201 `{new_version_id, source_version_id, status: "draft"}` | 404 / 409 source_not_released / 409 label_exists |
| GET | `/api/std/publish/versions` | any auth | `?document_id=` | 200 `{versions: [...]}` | — |
| GET | `/api/std/publish/timeline/{version_id}` | any auth | — | 200 `{events: [...]}` | 404 |

### 5.2 Derivation

| Method | Path | Auth | Body / Query | Response | Errors |
|---|---|---|---|---|---|
| GET | `/api/std/derive/strategies` | any auth | — | 200 `{strategies: [{name, status, description}]}` | — |
| GET | `/api/std/derive/links` | any auth | `?version_id=&strategy=&status=` | 200 `{links: [...]}` | — |
| POST | `/api/std/derive/rerun/{version_id}` | admin | `{strategies?: [...]}` | 200 `{results: {strategy_name: {...}}}` | 404 / 409 not_released |
| GET | `/api/std/derive/status/{version_id}` | any auth | — | 200 `{strategies: {name: {active, stale, failed}}}` | 404 |

### 5.3 既有 endpoint 守卫扩展

把 Wave 4 在以下 handler 里的 `_block_if_reviewing` 调用替换为 `_block_if_not_drafting`：

| Endpoint | Wave 4 状态 | Wave 5 |
|---|---|---|
| POST `/api/std/clauses/{cid}/lock` | 拦 review | + 拦 approved/released |
| PUT `/api/std/clauses/{cid}` | 拦 review | + 拦 approved/released |
| POST `/api/std/citation/insert` | 未拦 | + 拦 review/approved/released |
| POST `/api/std/clauses/{cid}/lock/break` | 未拦 | + 拦 released（admin 也不能）|

## 6. 关键数据流

### 6.1 流程 A：发布

```
[admin 点 [发布 v2.0]] (PublishSubTab)
  │
  └→ POST /api/std/publish/versions/{vid}
       ├─ guards: status='approved' check (else 409)
       ├─ Tx (FOR UPDATE):
       │   1. UPDATE std_document_version SET status='released'
       │   2. INSERT std_publish_event (event_type='published')
       │   3. INSERT agent_outbox (event_type='release_published',
       │                            payload={'version_id': vid})
       └─ 201 {released_at, outbox_event_id}

[outbox worker] (异步, 独立进程)
  │
  └→ poll agent_outbox WHERE status='pending'
       └→ release_published → derivation.runner.dispatch(version_id)
            └→ to_semantic_hint.run(...):
                 1. 读 bound data_element
                 2. 找 doc 的 prev active link
                 3. upsert hint + create link
                 4. mark stale (旧未覆盖)
                 5. 返回 DerivationResult
            └→ outbox event mark success / failed
```

### 6.2 流程 B：Fork

```
[admin 在 PublishSubTab 选 v1.0 (released) → [Fork 新版本]]
  │
  └→ POST /api/std/publish/fork {source_version_id, new_label='v1.1'}
       ├─ guards: source.status='released' (else 409)
       ├─ guards: UNIQUE (document_id, new_label) (else 409)
       ├─ Tx:
       │   1. INSERT std_document_version (status='draft', supersedes=source)
       │   2. CREATE TEMP TABLE clause_id_map(old_id, new_id)
       │   3. INSERT std_clause SELECT ... 改 id, version_id; 填 map
       │   4. INSERT std_data_element (含 binding 三列复制)
       │   5. INSERT std_term / std_value_domain
       │   6. INSERT std_reference (source_clause_id 走 map; target 同 doc 走 map, 跨 doc 保留)
       │   7. INSERT std_publish_event (event_type='forked')
       └─ 201 {new_version_id}
```

### 6.3 流程 C：手动重派生

```
[admin DeriveSubTab 选 v2.0 → [重派生]]
  │
  └→ POST /api/std/derive/rerun/{vid}
       ├─ guards: version.status='released' (else 409)
       ├─ 同步调用 derivation.runner.dispatch (不走 outbox, 等结果)
       └─ 200 {results}
```

## 7. 一致性、错误处理、安全

### 7.1 不变量

1. 同 `(strategy, target_kind, target_id)` 同时只一条 `status='active'` link（PARTIAL UNIQUE）
2. `agent_semantic_hints.std_derived_link_id IS NULL` ⊕ `IS NOT NULL`，前手工后派生互不覆盖
3. `std_data_element` binding 三元组要么全 NULL 要么全非 NULL（CHECK）
4. released 版本的所有 drafting 端点拦 409
5. fork 必须复制完整子图，FK 重映射在事务内完成
6. 单 strategy 失败不阻塞其他 strategy，单 source 失败不阻塞其他 source（spec §6.4 乐观发布）

### 7.2 错误分类

| 错误类型 | 例子 | 处理 |
|---|---|---|
| 守卫拒绝 | drafting 端点对 released 版本 | 同步 409 |
| 状态机违规 | 发布 status≠approved | 同步 409 + current_status |
| Strategy 内部异常 | 某 binding 失效 | source 进 failed list，不阻塞其他 source |
| Strategy 整体失败 | DB 短连 | result['ok']=false，不阻塞其他 strategy |
| Outbox 处理失败 | release_published handler 抛异常 | outbox 自带重试 |
| Fork 部分失败 | 任一表复制失败 | 整个事务回滚 |

### 7.3 安全

- 所有 `/api/std/publish/*` 写端点 `_require_admin_or_403`（复用 Wave 4 helper）
- `/api/std/derive/rerun/*` 同上
- 读端点 `_auth_or_401` 即可
- 守卫层在 handler 入口；repo 层不重复检查（按 Wave 1-4 风格）

## 8. 测试策略

### 8.1 测试清单（约 53 个新测试）

| 层级 | 文件 | 数量 |
|---|---|---|
| Migration schema | `test_migration_079.py` + `test_migration_080.py` | 8 |
| Repo | `test_publish_repo.py` | 8 |
| Repo | `test_link_repo.py` | 5 |
| Strategy | `test_semantic_hint_strategy.py` | 8 |
| Runner | `test_derivation_runner.py` | 4 |
| Publish handler | `test_publish_handler.py` | 7 |
| Derive handler | `test_derive_handler.py` | 6 |
| 守卫扩展 | `test_api_drafting.py` (extend) | +3 |
| 端到端 | `test_publish_to_derive_flow.py` | 4 |

### 8.2 关键 fixture

复用 Wave 4 conftest：`engine`、`fresh_clause`、`_client()`、`_auth_user()`。

新增 fixture（在 conftest）：
- `fresh_approved_version` — `fresh_clause` + UPDATE status='approved'
- `fresh_released_version` — `fresh_clause` + UPDATE status='released'

### 8.3 端到端关键场景

1. **happy flow**：起 round → close approved → 发布 → outbox worker 跑 → agent_semantic_hints 写入 + std_derived_link active
2. **fork flow**：released v1.0 → fork → v1.1 (draft) + 内容一致 + 后续可起 round
3. **stale flow**：v1.0 派生 5 hint → fork v1.1 删 1 个 data_element → 发布 v1.1 → 旧 link mark stale + 旧 hint.derived_status='stale'
4. **手工共存**：agent_semantic_hints 已有 1 行手工（link_id IS NULL）+ 派生写 5 行 → 总 6 行 + 手工行不动

### 8.4 不做

- 性能测试
- 前端 E2E
- 多 strategy 失败隔离的真实场景（Wave 6+ 加更多 strategy 时再做）

## 9. 路由总数变化

Wave 4 末尾 std_platform 23-25 routes → Wave 5 加 8 routes（4 publishing + 4 derivation）→ ~31-33 routes。

## 10. Wave 5 实施 checklist 概要

> 详细 plan 由 superpowers:writing-plans 单独生成

预期 ~10 task / ~9 impl commits，体量与 Wave 4 相当。

| # | Task | 文件数 | 测试 |
|---|---|---|---|
| 1 | migration 079 + 080 | 4 | 8 |
| 2 | publishing/{publish_repo, guards}.py | 3 | 8+5=13 (含 link_repo) |
| 3 | publishing handlers + 路由 | 2 | 7 |
| 4 | derivation/{strategy_base, link_repo}.py | 3 | 5 |
| 5 | derivation/strategies/semantic_hint.py | 1 | 8 |
| 6 | derivation/runner.py + outbox handler 注册 | 3 | 4 |
| 7 | derivation handlers + 路由 | 2 | 6 |
| 8 | drafting gate 扩展（_block_if_not_drafting 替换） | 1 | +3 |
| 9 | 前端 SDK + PublishSubTab + DeriveSubTab + 子组件 | 12+ | — |
| 10 | StandardsTab enable + 端到端测试 + push | — | 4 |

## 11. 与现有系统的映射

| 现有 | Wave 5 | 操作 |
|---|---|---|
| `agent_semantic_hints` 表（v7 P0-pre 落 DB） | 派生目标 | 加 3 列、不动手工行 |
| `sources` 表（已有） | binding 起点 | 被 std_data_element.bound_source_id FK 引用 |
| outbox（Wave 1） | 触发器 | 加 1 个 event_type handler 注册 |
| `_block_if_reviewing`（Wave 4） | 守卫 | 替换为 `_block_if_not_drafting` |
| `std_document_version.status` CHECK（migration 071） | 状态机 | 已含 'released'，复用 |
| `std_data_element` 表（P0） | binding 载体 | 加 3 列 |

## 12. 未决事项 / 未来工作

1. **派生回滚**：发布出错或 stale 累积太多时的批量清理 — Wave 6+
2. **跨 doc 派生约束**：同一物理列被两个 doc 派生（理论冲突）—— Wave 5 不防，靠 admin 操作意识
3. **value_domain 解析复杂值约束的细节**：spec §11 提到的 enum / range / regex 三种映射，Wave 5 仅做 enum + range 简单情况
4. **outbox event 失败的人工干预**：dead-letter 后的可视化与重试 UI — Wave 6+
5. **下游派生数量爆炸时的性能**：100+ data_element 派生延迟，Wave 5 不压测，等到大数据量场景再优化

## 13. 参考

- 父 spec: `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`
- Wave 4 spec: `docs/superpowers/specs/2026-05-17-std-platform-wave4-review-subtab-design.md`
- Wave 4 plan: `docs/superpowers/plans/2026-05-17-std-platform-wave4-review-subtab.md`
- v15.7 测绘 QC defect_taxonomy（未来 to_defect_code 派生目标）
- v7 P0-pre `agent_semantic_hints / value_semantics / sources.synonyms`（未来其他 strategy 派生目标）
