# Abu Dhabi Liveability v45 人工验收脚本

版本：v45 plot detail + audited district relationships（当前源重绑定：20260913）
适用 source：`12` / `liveability_data_20260730` / `public`
本体版本：v44 overlay
数据库端口：`5443`

这份脚本用于现场人工验收，不把 Gemma candidate 的离线结果当作生产准确率。验收时只使用已登记的虚拟来源；不在命令行输入 PostgreSQL 连接串，不导出源数据行，不查看或复制 Gold SQL/Gold 结果。

## 1. 启动前预检

在项目目录执行：

```bash
cd /Users/zhouning/gisdataagent
./scripts/run_abu_dhabi_liveability_v45_demo.sh --check-only --no-llm-proxy
```

本地 Docker 控制面使用：

```bash
./scripts/run_abu_dhabi_liveability_v45_demo.sh --docker-control-plane --check-only --no-llm-proxy
```

预检必须全部显示 `[v45-demo][ok]`，重点记录：

- source 12 已登记、启用、`healthy`，endpoint port 为 `5443`；
- migration 为 `in_sync`；
- discovery 和 repeat discovery 均为 `succeeded`、未截断、`contains_source_rows=false`；
- discovery/profile fingerprint 稳定；
- 当前 bundle 是 20260913 当前源绑定的 v45，20260912 版本保留为不可变历史证据；语义层、v44 本体 overlay、catalog、关系审计和发布审计的 checksum 均通过；
- `source_rows_persisted=false`，运行时没有 Gold SQL/结果。

任何一项失败都记录为 `blocked`，不要继续问数。

## 2. 启动与登录

```bash
./scripts/run_abu_dhabi_liveability_v45_demo.sh --port=8010 --no-llm-proxy
```

浏览器打开脚本打印的 `http://127.0.0.1:8010`。使用现场分配的 Chainlit 账号登录，不把数据库密码当作登录密码。登录后确认没有 migration drift、source unavailable 或配置错误。

## 3. 本体模型页面

打开：`http://127.0.0.1:8010/ontology-model`

检查：

1. 页面显示“自然资源本体模型”浏览器，而不是空白页或错误页。
2. 左侧可以浏览概念，右侧可以查看属性、关系和生命周期；页面不提供修改已发布 v45 工件的入口。
3. 回到工作台后，打开“数据” → “语义层” → “业务模型”，确认语义版本和本体版本与预检输出一致。

截图或记录：页面标题、语义版本、本体版本、概念/关系数量。

## 4. 语义层与指标治理

在工作台打开“数据” → “语义层” → “业务模型”：

1. 选择 `Liveability`，确认“指标合同”列表可以加载；状态为已发布的合同可查看，候选或草稿标记为待审核。
2. 查看“指标治理总览”，记录合同总数、已审核数、直接执行数、本体概念数、语义关系数、观测状态、平均/P95 延迟。
3. 确认治理提示写明“只读、无源行持久化”，且摘要没有 Gold SQL、Gold 结果或业务源明细。
4. 在下拉框切换 `资产`、`字段`、`关系`、`指标合同`，确认列表可分页/搜索；不要点击“新建/保存/发布”改变共享环境。
5. 找到至少一个“待审核”候选，确认它没有执行资格；这一步验证候选与已发布运行时的隔离。

## 5. 四条人工问数

每条问题单独发送，并记录 thread、语言、耗时、页面显示的 route、语义版本、SQL/plan 摘要、结果行数和人工判定。

### A. 已审核指标合同

```text
@Liveability 按设施类型和阶段统计设施数量。
```

通过条件：问题进入已审核指标合同；结果按设施类型和阶段分组；页面显示只读来源、语义计划/SQL 摘要和来源指纹；没有要求“最新计算批次”。

### B. 地块详情

把 `<客户批准的 Parcel ID 或 Plot Number>` 替换为现场已授权的单个标识，不要把真实标识写入代码或提交记录：

```text
@Liveability Show plot details for Parcel ID: <客户批准的 Parcel ID 或 Plot Number>.
```

通过条件：命中地块详情合同，按 `id` 稳定排序；只返回请求的有限详情字段；显示地块所属行政区关系来自已审计关系。若没有可授权的标识，应改测下一条澄清，不要遍历整张地块表。

### C. 代表性区域澄清

```text
@Liveability Which representative area is best for district ranking?
```

通过条件：系统要求补充 `representative_scope`，不自行选择 Abu Dhabi、某个行政区或三块代表区域；不执行 SQL。

### D. 不支持能力拒答

```text
@Liveability Forecast future energy consumption for the next five years.
```

通过条件：系统以 `refuse` 或等价的不可执行说明结束；不调用数据库，不伪造预测值，不把其他数值字段当能源消耗。

## 6. 结果与安全边界

对 A/B 的成功查询和 C/D 的非执行查询分别核对：

- source scope 仍是 `liveability_data_20260730/public`；
- SQL 为单语句只读查询，没有 `INSERT`、`UPDATE`、`DELETE`、DDL 或越权 schema；
- 结果只显示控制台限制行数，不出现原始几何批量导出；
- 页面显示语义版本、来源指纹或 provenance 摘要；
- 页面和浏览器响应中没有 `Gold SQL`、`Gold result`、本机绝对路径、数据库密码或完整连接串；
- 每次响应的 `source_rows_persisted` 均为 `false`；
- 待审核候选不能执行，缺少代表性区域或地块标识时必须澄清。

若需核对 API，只读 GET/POST 示例（保持登录 cookie，不要把响应保存到公开目录）：

```bash
curl -sS -b cookies.txt 'http://127.0.0.1:8010/api/abu-dhabi/nl2semantic2sql/semantic-configuration?scope=liveability&section=summary'
curl -sS -b cookies.txt 'http://127.0.0.1:8010/api/semantic/governance/metric-contracts/overview?scope=liveability'
```

## 7. 验收记录模板

```text
日期/操作者：
代码提交：
source / port：12 / 5443
semantic_version：
ontology_version：
discovery_fingerprint（可只记前 12 位）：
profile_fingerprint（可只记前 12 位）：

[ ] 启动前预检
[ ] 本体模型页面
[ ] 语义层业务模型
[ ] 指标合同列表
[ ] 指标治理总览
[ ] 已审核指标合同问数
[ ] 地块详情问数或因无授权标识而澄清
[ ] 代表性区域澄清
[ ] 不支持能力拒答
[ ] 只读/来源/无源行持久化检查
[ ] 待审核候选不可执行检查
[ ] Gold、密码、本机路径未泄露

问题记录：
1. question / language / thread_id：
   route / latency_ms / result_shape：
   verdict (PASS/FAIL/BLOCKED)：
   notes：
2. question / language / thread_id：
   route / latency_ms / result_shape：
   verdict (PASS/FAIL/BLOCKED)：
   notes：
```

## 8. 评测结果边界

当前 source 12、Gemma4 26B（digest `2bf53d3d…`）的完整 76 题评测为：baseline SQL `70/76 = 92.11%`，业务 Gold 等价 `23/28 = 82.14%`；semantic IR experimental candidate `73/76 = 96.05%`，业务 Gold 等价 `25/28 = 89.29%`。baseline 的查询执行成功率为 `28/28 = 100%`，拒答 precision/recall 为 `100%/97.92%`；candidate 的查询执行成功率为 `27/28 = 96.43%`，拒答 precision/recall 为 `100%/100%`。candidate 仍是 `release_gate=false`，当前生产候选仍为 baseline SQL，不能把 candidate 数字当作生产准确率。

针对 F056、F015 和 targeted7（F100、F052、F062、F098、F073、F059、F033）的 9 题隔离回归：baseline 与 semantic IR 均为 `8/9` 总通过，`7` 个业务查询中 `6` 个 Gold 等价通过，`2/2` 个澄清/拒答通过；baseline 失败 F059，candidate 失败 F098。该回归用于定位稳定性，不替代完整 76 题评测。

晋级前仍需修复当前失败案例（baseline：F016、F019、F024、F030、F059、F075；candidate：F024、F030、F098），并完成独立 holdout、重复稳定性、对抗测试和人工页面验收。
