# ADR-295: Cross-Store Recovery Identity Binding

状态：已采纳，合同、durable authority、恢复准入协调器、PostgreSQL durable controller ledger 和 disposable 联合认证已实现；生产事务能力仍未完成  
日期：2026-08-25

## 背景

控制账本和对象存储可以分别完成恢复，但两边可能指向不同的源版本、不同的租户集合，或者
一个已恢复而另一个缺少对象。已有的控制账本 manifest（ADR-293）和对象 manifest（ADR-294）
各自有效，却没有一个共同的恢复身份来阻止这种错配。

## 决策

新增 `data_agent.platform_runtime.cross_store_recovery` 合同：

- 绑定排序后的租户集合；
- 绑定源 `ResourceVersion` 引用和源内容 SHA-256；
- 绑定控制账本 manifest SHA-256 与对象 manifest SHA-256；
- 对全部字段计算 `gda.cross_store_recovery_binding.v1` 指纹；
- source/restored 必须以同一个 binding 完整对账，任一 store 的 manifest、源版本或内容指纹
  漂移都拒绝恢复准入。

该 binding 是恢复身份和 admission evidence，不是两阶段提交协议。provider 已提交但另一侧
尚未提交的情况仍由既有 cross-store recovery state machine 处理，不能因为 binding 存在就自动
重放不确定的 provider side effect。

## 取舍

| 方案 | 结果 |
| --- | --- |
| 只比较控制账本 | 漏掉对象缺失、对象租户越界和字节恢复漂移 |
| 只比较对象 manifest | 无法证明恢复后的控制记录属于同一源版本 |
| 用一个 binding 绑定两份 manifest | 恢复身份明确，且不要求跨 provider 分布式事务 |

选择第三项。binding 只保存摘要和源身份，不复制控制账本行或对象内容；完整内容仍由
ADR-293/294 各自的恢复合同负责验证。

## 已验证范围

`data_agent/test_cross_store_recovery.py` 验证：

- 同一租户集合、源版本和两份 manifest 的 binding 可稳定重放；
- 控制与对象租户集合不同立即拒绝；
- 源 ResourceVersion、源内容 SHA、控制 manifest 或对象 manifest 任一漂移均拒绝；
- binding 指纹篡改拒绝。

对象恢复、控制账本恢复和跨 store binding 联合回归共 `28 passed`；Ruff 与 Python 编译通过。

随后新增 migration `232_cross_store_recovery_binding_authority.sql` 和
`PostgresCrossStoreRecoveryBindingAuthority`。authority 按 covered tenant 写入同一份 binding
证据副本，使用强制 RLS、append-only trigger 和 `SECURITY DEFINER` 受控写函数；同 binding
重放返回已有记录，同一源 `ResourceVersion` 的不同 binding fail closed。disposable
PostGIS + MinIO 联合认证已通过：两个租户各写入 authority、重启后读回、跨租户 current 隔离，
同源 binding 漂移拒绝；MinIO 源/恢复对象 manifest 先完成显式 VersionId remap 对账。认证报告
`.tmp/cross-store-recovery-binding/acceptance-report.json` 的最新 canonical `report_sha256` 为
`1a89ff492a19560752f53fec0d7ba5907169b5fb9d1028460ee0ca7d1ce0569c`，文件 SHA-256 为
`7ec0c58f9fd262c896e5758b9bfc127f12f98532bbb35b63d5f2b3ffd9ee732f`。报告中的十一项功能检查和五项
清理检查均为 `true`；controller ledger scope 为 `temporary_postgresql_database`。

本轮又新增 `CrossStoreRecoveryAdmission`。恢复 controller 只需向该入口提供 source/restored
控制账本 manifest、source/restored 对象 manifest 和租户 authority 集合；入口先完成两侧
manifest 对账，再构造 source binding，逐租户持久化并重新读取 durable binding，任一租户缺失、
authority 身份错配、对象 VersionId 未显式允许重映射或 read-back 漂移都会拒绝准入。联合认证脚本
已改为调用这一入口，而不是由脚本自行编排 authority 写入。

在此之上新增 `CrossStoreRecoveryController` 合同，固定 `planned -> admitted -> completed`
主路径，并支持 `reconciliation_required -> reconciled -> admitted` 和
`failed_closed -> await_operator`。事件、快照和状态指纹均为 append-only ledger 协议。
新增 migration `233_cross_store_recovery_controller_authority.sql` 和
`PostgresCrossStoreRecoveryControllerLedger`：每个 covered tenant 保存同一份快照副本，采用强制
RLS、append-only trigger、`SECURITY DEFINER` 受控写函数和事务内逐租户切换 tenant context；
planned 空租户快照只作为 controller 初始化状态，admitted 以后必须覆盖完整 authority tenant set。
同快照重放幂等，事件链跳过 predecessor、篡改前缀或租户副本漂移均 fail closed。该 ledger 是
PostgreSQL durable controller state authority，但仍不是 PostgreSQL 与对象 provider 的分布式事务。

本轮把 controller 接入既有 durable projection recovery job，而不是另起一条 generic worker：
`ProjectionRecoveryControllerGuard` 在 job claim 后先校验 plan 对应的 admission bundle，只有
`planned -> admitted` 或已有合法 controller 状态才允许进入 projection provider；provider 未知结果、
目标漂移和 compensation-required 会推进 controller 的 `reconciliation_required`，只有
projection checkpoint authority 已提交后才允许 `reconciled -> admitted -> completed`。controller
与 projection ledger 各自保留自己的 append-only 证据，租约丢失时不写 terminal settlement。
部署侧 `ProjectionRecoveryControllerAdmissionBundleResolver` 从 server-owned JSON 读取按
`plan_sha256` 索引的 binding/tenant-copy evidence，`ProjectionRecoveryControllerBindingResolver`
为每个 job 使用 PostgreSQL durable controller ledger；Compose 的 projection-recovery profile 已
提供可选 `GDA_PROJECTION_RECOVERY_CONTROLLER_ADMISSION_FILE`。未配置 bundle 时不改变现有
projection-only worker 行为，配置但证据缺失、租户不覆盖或 binding 指纹错误则 fail closed。

## 边界与后续

controller durable authority 的专项回归为 `4 passed`；配置临时 PostGIS 后真实回归为 `4 passed`，
覆盖 planned 初始化、两租户副本、重启 current/history、幂等追加、事件链篡改拒绝和第三方租户隔离。

projection job/controller 适配层回归为 `27 passed`，覆盖 controller admission/settlement、未知
provider 结果、进程重启后的 projection ledger 重读、provider side effect 不重复执行和 admission
bundle 的 plan/tenant 绑定。该 bounded deployment evidence 仍不等同于生产 recovery controller
HA、workload identity/OIDC、provider 原生复制/PITR、故障注入或 RPO/RTO。

随后将该适配接入现有 PostgreSQL recovery rehearsal，真实执行 `233` 号 migration 和
durable queue/lease。2026-08-25 报告的 `39/39` 检查通过，其中新增
`durable_controller_settles_projection_job` 与 `durable_controller_blocks_unknown_provider_replay`；
报告 canonical `report_sha256` 为
`379da6be675ac1630915fd0253b04858a1e5b089b54030925fc485388495d264`，文件 SHA-256 为
`c6ad8dd194468d3b097609f73e86fd9edc5b371ad3ce47ae34c2ede67a277464`，范围仍为
`temporary_database_only`。

本轮补齐了 `k8s/optional/projection-recovery-worker` 部署 profile。它不进入默认
`k8s/base`，Deployment 默认 `replicas: 0`，使用独立 ServiceAccount、UID/GID 10001、只读根文件系统、
无 Kubernetes API token 和单独的 PostgreSQL/MinIO/DNS NetworkPolicy。worker 只从两个环境提供的
Secret 读取租户 ID 和按 `plan_sha256` 索引的 admission bundle；resolver 还会把 binding 的 source
ResourceVersion 和 source content SHA-256 与 sealed plan 的 `desired_state` 精确对账，避免错误
证据被放到正确 key 下；provider credential 不写入 profile。
没有 admission Secret 时 Pod 不会被误启动，PostGIS/pgvector 的 row bundle 仍需环境-owned volume，
缺失时由 runtime resolver fail closed。离线 YAML/Kustomize 合同测试 `5 passed`，该 profile 仍是
sandbox deployment contract，不代表 recovery controller HA、OIDC/workload identity、PITR 或 RPO/RTO。
admission bundle 的严格 schema、canonical 序列化和原子轮换见 [ADR-296](adr-296-recovery-admission-bundle-rotation.md)。

这条认证证明的是一个 disposable 恢复任务中的恢复准入、durable binding 写入、durable controller
事件链和重启读取，不是生产跨 store atomic commit、复制、PITR、HA、RPO/RTO 或 provider 故障注入。
后续仍需把该 ledger 部署到正式 recovery controller，接入生产 workload identity、备份与恢复策略，
并分别认证真实 provider 的断连、硬杀、网络分区、重复提交和恢复时间边界。
