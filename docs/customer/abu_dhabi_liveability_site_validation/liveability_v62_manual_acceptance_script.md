# Abu Dhabi GIS Data Agent v62 人工验收脚本

## 1. 验收边界

本脚本验证当前发布组合：

- Liveability source：`12`，数据库 `liveability_data_20260730`，端口 `5443`
- Semantic：`abu-dhabi-liveability_data_20260730-v62-ontology-authority-alignment-20260917`
- Ontology：`abu-dhabi-liveability-ontology-v61-authority-alignment-20260917`
- 默认智能问数路线：Semantic IR（元数据检索、严格校验、编译器生成 SQL）

这不是“任意问题 100% 正确”的声明。当前形式本体执行门禁只覆盖已经审核的业务类；物理表不能因为存在于数据库中就自动成为本体类。未发布关系、未定义指标和不支持的阶段必须澄清或拒答。

## 2. 前置连通性

执行：

```bash
cd /Users/zhouning/gisdataagent
nc -vz 10.255.254.109 5443
curl --noproxy '*' -fsS http://10.255.254.81:11434/api/tags | jq '.models[] | select(.name == "gemma4:26b") | {name,digest}'
```

通过标准：

1. `10.255.254.109:5443` 可连接。
2. 模型清单中存在 `gemma4:26b`。
3. 如果任一检查失败，停止问数准确率验收，记录为“基础设施阻塞”，不要记为模型答错。

## 3. 启动系统

终端一启动后端：

```bash
cd /Users/zhouning/gisdataagent
GDA_DISABLE_LLM_PROXY=1 \
GDA_LLM_PROVIDER=ollama \
GDA_LLM_MODEL=gemma4:26b \
GDA_LLM_BASE_URL=http://10.255.254.81:11434/v1 \
GDA_LLM_API_KEY=ollama \
OLLAMA_API_BASE=http://10.255.254.81:11434 \
GDA_LLM_ENABLE_THINKING=false \
./.venv/bin/chainlit run data_agent/app.py --host 127.0.0.1 --port 8000 -w
```

终端二启动当前 React 前端：

```bash
cd /Users/zhouning/gisdataagent/frontend
VITE_PROXY_TARGET=http://127.0.0.1:8000 npm run dev -- --host 0.0.0.0
```

打开：

- 主页面：`http://127.0.0.1:5173/`
- 本体模型：`http://127.0.0.1:5173/ontology-model`
- 指标管理：`http://127.0.0.1:5173/metric-management`

独立本体和指标页面需要登录。使用现有 GIS Data Agent 账号；只有 `admin` 或 `analyst` 角色应看到编辑能力。

## 4. 本体模型验收

打开 `/ontology-model`。

检查：

1. 页面标题为“行业本体模型”，不是数据库表清单页面。
2. 可以选择 DMT/Liveability 相关本体范围，并看到类、属性、关系数量。
3. 业务类与来源表示分离；不能把 `public.xxx` 物理表名直接显示为业务本体类定义。
4. 点击“创建草稿”，在草稿中新增或修改一个测试类/属性。
5. 执行校验和差异查看；修改只进入草稿，不得原地覆盖当前发布本体。
6. 放弃测试草稿，确认当前发布版本未改变。

失败条件：看不到 DMT/Liveability 范围；无法创建草稿；物理表被直接当成本体类；未发布修改立即进入运行时。

## 5. 指标管理验收

打开 `/metric-management`。

检查：

1. 页面直接进入“指标管理”，下拉类型默认为“指标合同”。
2. 页面不得出现 `unsupported scope or entry_type`。
3. “指标治理总览”显示语义版本、本体版本、合同总数、已审核数、直接执行数和指标组合数。
4. 展开带“指标组成”的合同，至少应显示以下内容中的适用项：
   - 组成规则和业务粒度
   - 阶段/字段映射
   - 维度
   - 度量及聚合方式
   - 数据范围和直接执行边界
5. 点击编辑时只生成版本草稿；不发布草稿，确认当前问数运行时不变。

失败条件：只有合同名称而没有组成逻辑；数据范围、维度和度量均为空；页面加载为 scope/entry_type 错误。

## 6. 智能问数验收

每道题使用新的对话，记录：问题、route、profile、模型名称和 digest、语义版本、SQL 是否执行、列名、行数、耗时、结论。

### 6.1 审核指标合同控制题

```text
@Liveability 按设施类型和阶段统计设施数量。
```

通过标准：直接执行；返回设施类型、阶段、设施数量；不得要求补充已经明确的业务对象和统计操作。

### 6.2 自由语义 IR 明细题

```text
@Liveability For AL MANHAL, list all domain scores (existing).
```

通过标准：只返回当前批准计算版本的一行，而不是多个历史计算版本；领域评分字段完整；执行证据包含当前版本策略和有效行政区策略。

### 6.3 自由语义 IR 排序题

```text
@Liveability 列出 AP50 阶段综合宜居性评分高于 82 分的行政区，显示行政区名称、所属市和综合评分，并按评分从高到低排序。
```

通过标准：执行而非澄清；结果只包含所需业务字段；所有评分大于 82；按评分降序。

### 6.4 地图联动题

```text
@Liveability 在地图上展示 AP50 阶段相对 Existing 阶段综合宜居性评分提升最大的 15 个行政区；提升值定义为 AP50 评分减去 Existing 评分。按提升值分级设色，点击区域时显示行政区名称、所属市、Existing 评分、AP50 评分和提升值。
```

通过标准：聊天结果与地图使用同一个查询结果；地图自动出现行政区要素和分级设色；点击弹窗字段与问题一致。不得为该问题编写前端题目专用分支。

### 6.5 审核空间关系题

不要加 `@Liveability`，让系统按业务对象自动路由：

```text
Which recorded master plan projects overlap Al Saadiyat Island, when were they approved, and who are the developers?
```

通过标准：使用审核的行政区—总体规划边界 `ST_Intersects` 关系；位置过滤绑定 `udm_district.nameenglish`；不得把地名过滤到项目名称。当前严格旧 Gold 还包含用户未明确要求的项目 ID、状态和重叠面积，因此人工功能验收以“60 条空间重叠记录及问题明确要求的字段正确”为准，旧 Gold 投影差异须单独记录，不能通过硬编码补列刷分。

### 6.6 治理拒答控制题

```text
@Liveability 哪个区域的宜居性最好？
```

通过标准：询问“最好”的指标和比较口径，不得自行发明综合指标。

```text
@Liveability 在地图上展示 Existing、AP25、AP50 三阶段持续提升的行政区。
```

通过标准：指出当前发布阶段域不包含 AP25，不能伪造 AP25 数据。

## 7. 无硬编码检查

执行：

```bash
cd /Users/zhouning/gisdataagent
rg -n 'ABU_DHABI_CUSTOMER|LIVEABILITY_CUSTOMER|Al Saadiyat|overlap_sqm|evaluation_private' \
  data_agent/governed_virtual_nl2sql.py \
  data_agent/semantic_query_ir.py \
  data_agent/ontology/semantic_execution.py
```

通过标准：生产代码无命中。题目文本可以存在于测试文件，但不得存在于生产路由、编译器、提示词选择和答案生成逻辑中。

## 8. 验收记录表

| 检查项 | 结果 | route/profile | 语义/本体版本 | 行数 | 延迟 | 备注 |
|---|---|---|---|---:|---:|---|
| 本体模型与草稿 |  |  |  |  |  |  |
| 指标组成逻辑 |  |  |  |  |  |  |
| 设施类型×阶段 |  |  |  |  |  |  |
| AL MANHAL 领域评分 |  |  |  |  |  |  |
| AP50 > 82 |  |  |  |  |  |  |
| 地图联动 |  |  |  |  |  |  |
| Saadiyat 空间关系 |  |  |  |  |  |  |
| 模糊指标澄清 |  |  |  |  |  |  |
| AP25 治理拒答 |  |  |  |  |  |  |
