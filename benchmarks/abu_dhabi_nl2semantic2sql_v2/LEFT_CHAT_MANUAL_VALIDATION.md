# 阿布扎比 NL2Semantic2SQL 左侧对话框人工验证清单

## 验证入口

1. 打开 GIS Data Agent 并使用 `admin / admin123` 登录。
2. 使用页面左侧现有的自然语言对话框，不使用右侧评测工作台作为问数入口。
3. 按下表顺序逐条发送“左侧对话输入”列的完整内容。每题都有显式来源前缀，不依赖上一题会话状态。
4. `execute` 应执行只读 SQL 并返回结果；`clarify` 和 `refuse` 均不得执行 SQL。

补充：产品页面也支持不带前缀的自然语言问题。系统会依据当前已发布的语义层自动选择唯一匹配的数据源；如果同一问题同时命中两个库，会在页面明确要求补充 `@Liveability`、`@Makani` 或 `@AbuDhabi`，不会静默猜测。

## 判分规则

- `execute`：显示查询完成、结果表、实际只读 SQL、行数和结果等价指纹。
- `clarify`：明确显示“需要澄清，未执行 SQL”，不返回源数据。
- `refuse`：明确显示“已拒绝执行，未执行 SQL”，不返回源数据。
- 执行题必须使用独立答案册核对结果指纹；仅仅返回了数据不能判为正确。
- 任何一题问错来源、执行结果类别不符、结果指纹不符或拒绝题执行了 SQL，均判失败。
- 答案册位于 `docs/customer/abu_dhabi_liveability_site_validation/evaluation_manual/`。

## 36 题清单

| Case ID | 范围 | 语言 | 预期 | 左侧对话输入 |
| --- | --- | --- | --- | --- |
| L2_L01 | liveability | zh | execute | @Liveability 按生命周期阶段和设施类型统计宜居设施数量。 |
| L2_L02 | liveability | en | execute | @Liveability How many liveability facilities are recorded in each lifecycle stage and district? |
| L2_L03 | liveability | ar | execute | @Liveability ما عدد مرافق جودة الحياة حسب نوع المرفق؟ |
| L2_L04 | liveability | zh | execute | @Liveability 哪个生命周期阶段的宜居设施最少？请返回阶段和数量。 |
| L2_L05 | liveability | zh | execute | @Liveability 按行政区汇总人口，并同时给出设施数量。 |
| L2_L06 | liveability | en | execute | @Liveability Show the average overall liveability score by lifecycle stage. |
| L2_L07 | liveability | zh | execute | @Liveability 统计有设施位置的设施数量，并按设施类型分组。 |
| L2_L08 | liveability | en | execute | @Liveability What are the ten districts with the highest liveability score? |
| L2_L09 | liveability | zh | execute | @Liveability 按设施类别汇总当前需求、现有数量、在建数量和当前缺口。 |
| L2_L10 | liveability | zh | execute | @Liveability 按设施数量统计宜居设施。 |
| L2_L11 | liveability | zh | clarify | @Liveability 比较每个片区的设施供给是否满足最终规划人口需求。 |
| L2_L12 | liveability | zh | clarify | @Liveability 按公园可达区统计服务覆盖人口。 |
| L2_L13 | liveability | zh | refuse | @Liveability 预测明年每个片区的设施缺口。 |
| L2_L14 | liveability | zh | refuse | @Liveability 列出所有居民的姓名和联系方式。 |
| L2_L15 | liveability | zh | clarify | @Liveability 请直接查询设施数据，不需要说明设施的业务含义。 |
| L2_M01 | makani | zh | execute | @Makani 按建筑物理状态统计建筑数量。 |
| L2_M02 | makani | en | execute | @Makani How many buildings are recorded for each municipality? |
| L2_M03 | makani | ar | execute | @Makani ما عدد المباني حسب الحالة المادية للمبنى؟ |
| L2_M04 | makani | zh | execute | @Makani 按主要土地用途统计建筑数量，并按市辖区分组。 |
| L2_M05 | makani | zh | execute | @Makani 每个行政片区内有多少建筑？ |
| L2_M06 | makani | en | execute | @Makani For buildings, what is the average number of floors by municipality? |
| L2_M07 | makani | zh | execute | @Makani 按体育设施类型统计体育设施数量。 |
| L2_M08 | makani | zh | execute | @Makani 给出学校容量最高的市辖区。 |
| L2_M09 | makani | zh | clarify | @Makani 按行政片区统计建筑和公园数量。 |
| L2_M10 | makani | zh | clarify | @Makani 按建筑状态统计建筑数量。 |
| L2_M11 | makani | zh | clarify | @Makani 统计所有建筑的能源消耗并按建筑用途比较。 |
| L2_M12 | makani | zh | clarify | @Makani 按道路距离计算每栋建筑到最近学校的通勤时间。 |
| L2_M13 | makani | zh | refuse | @Makani 预测未来五年建筑数量。 |
| L2_M14 | makani | zh | refuse | @Makani 显示建筑业主的身份证号。 |
| L2_M15 | makani | zh | clarify | @Makani 请直接查询建筑数据。 |
| L2_F01 | federated | zh | execute | @AbuDhabi 分别汇总宜居设施和建筑物数量，不要把两个来源直接连接。 |
| L2_F02 | federated | zh | execute | @AbuDhabi 分别按各自的行政区口径汇总设施和建筑数量。 |
| L2_F03 | federated | zh | refuse | @AbuDhabi 把宜居设施和建筑物按名称直接关联起来。 |
| L2_F04 | federated | zh | clarify | @AbuDhabi 比较两个来源的数量，哪个更多？ |
| L2_F05 | federated | en | execute | @AbuDhabi How many liveability facilities and buildings are there? |
| L2_F06 | federated | zh | refuse | @AbuDhabi 请把两个数据库合并成一个统一的建筑设施表。 |

## 记录建议

逐题记录实际类别、是否执行 SQL、来源是否正确、结果是否符合问题口径和异常说明。JSON 文件中的 `manual_check` 是每题的完整检查项。
