# ADR-244: Bind JQDLTB Transformation Contracts to the Scheduler Execution Plan

状态：已采纳  
日期：2026-08-23

## 背景

AR-0 已经有审批、编译和本地执行器，但审计 workflow 与 transformation workflow 之前没有调度层连接。若调度任务只传租户、run 和 source version，任务就可能在运行时重新选择规则；若把规则散落在 DolphinScheduler 参数中，又无法和控制面的审批证据保持同一份身份。

## 决策

新增独立的 JQDLTB transformation DolphinScheduler definition 和 deployment/submit 脚本。

执行计划 artifact 使用 `gda.dolphinscheduler_jqdltb_transformation_plan.v1`，其 manifest 同时包含：

- DolphinScheduler workflow binding；
- `mode=execute` 的完整 JQDLTB contract；
- contract 的 `plan_sha256`、`contract_sha256` 和 ApprovalCase 引用。

部署时重新读取 ApprovalCase authority，要求权威 ApprovalCase 与 contract 完全一致，并要求 `target_fingerprint == plan_sha256`。运行提交时，PlatformRun 的 policy decision 指向该 execution-plan artifact；DolphinScheduler raw task 只携带已经编译的 contract，执行器再把请求 contract 与 policy 指向的 plan artifact 做一致性校验。

审计 workflow 和 transformation workflow 使用不同的 definition URN、capability、workflow name 和 endpoint，不能互相替代。transformation executor 仍只创建 candidate layers 和证据，不创建 `DataProductVersion`。

## 取舍

- contract 同时存在于 execution-plan manifest 和 raw task 请求中，增加了一次一致性校验，但避免调度器运行时依赖数据库查询或动态选策略。
- scheduler plan artifact 是 provider-specific 的；未来切换编排器时需要生成新的 binding，但 JQDLTB contract、审批和执行证据仍可复用。
- deployment 必须连接 ApprovalCase authority，离线生成一个“看起来可执行”的 workflow 不再被视为部署成功。

## 后果

- 任务、PlatformRun、policy decision、ApprovalCase 和 executor admission 形成可追溯闭环。
- contract drift、plan drift、错误 workflow 复用会在部署、提交或执行前失败。
- DolphinScheduler 仍不负责业务审批、质量判定或产品发布。

## 重审条件

- 引入第二个编排器并需要共享非 provider-specific execution plan；
- JQDLTB contract 需要外部密钥或敏感配置，不能安全地随 raw task 传递；
- candidate 到 `DataProductVersion` 的发布 gate 已经定义并需要新的平台命令类型。
