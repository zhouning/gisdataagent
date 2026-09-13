# 重庆人口与人口结构就绪度验证报告（需求6）

## 结论

- 已形成 `uwm.population_demographic_readiness.v1` 人口证据目录、人口结构契约与 UWM 动态就绪产品。
- Bundle：`population-demographic-38249d443b90fe4e1d34`。
- 登记 4 类证据：2021 区县人口背景、2020 GHSL 人口空间代理、GHSL 行政区对齐、2021 人口下采样代理。
- 区县统计包含 39 个区县；GHSL 行政对齐包含 1017 个行政单元；下采样文件包含 852 行代理记录。
- 权威当前人口、预测人口均为 `null`；14 个人口结构通道全部不可用。
- UWM 人口状态、队列转移、出生死亡、迁移、家庭转变、规划响应、服务需求传播、增长预测、反事实 rollout 和不确定性校准全部关闭。

## 最大声明

`observed_population_evidence_catalog_demographic_contract_and_uwm_population_dynamics_readiness`

现有产品可支持人口空间证据发现、代理覆盖审计、空间粒度与年份说明，以及未来人口主数据和动态事件的接入合同；不能支持当前权威人口、性别、年龄、国籍、公民身份、家庭构成、迁移、增长趋势、服务需求预测或规划影响结论。

## 关键边界

- GHSL 与下采样人口是代理，不是人口普查微观数据。
- 2021 区县总量是脆弱背景证据，不等于当前人口或人口结构。
- 单一横截面不能建立增长、迁移或家庭转变机制。
- 缺少某人口分组数据不代表该分组人数为零。
- 规划容量不等于已经观测到的人口迁移响应。

## 验证命令

`python scripts/verify_population_demographic_readiness_chongqing.py data/uwm_public_proxy/chongqing_central/population_demographic_readiness_chongqing`
