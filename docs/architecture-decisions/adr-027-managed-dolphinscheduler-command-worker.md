# ADR-027：以受管进程承载 Tenant-Scoped DolphinScheduler Command Worker

**Status**: Accepted

**Date**: 2026-07-25

**Decision owners**: Platform Architecture, DataOps, Data Platform, Security, SRE

**Related decisions**: ADR-007、ADR-023、ADR-024、ADR-025、ADR-026

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-025 先建立了 PostgreSQL command outbox 和 `run_once` consumer library，但库函数本身没有进程生命周期、信号处理、部署配置或健康投影。直接把轮询放回 API 请求线程会重新引入请求生命周期与命令可靠性的耦合；引入 Kafka、RabbitMQ 或独立微服务则会增加第二个交付事实源和新的恢复边界。

本阶段需要一个可以由现有进程管理器或容器编排器托管的最小 worker，同时保留 PostgreSQL outbox 对 command 状态的唯一权威。它只解决“谁在运行、何时领取、如何退出、如何被探测”，不改变 Run、observation、provider instance 或 outbox 的归属。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. API/脚本周期调用 `run_once` | 没有新进程 | 调用者必须自行处理 drain、重试、健康和租约边界，容易把可靠交付退回 best effort | 拒绝 |
| B. 引入外部 broker 或独立 command service | 可扩展、可唤醒 | 新增 broker、凭据、部署、重复投递和第二套恢复语义，当前没有吞吐证据支持 | 暂缓 |
| C. 复用 consumer 的受管模块化进程 | 复用已验证的 claim/lease/adapter 边界；可以由 systemd/Kubernetes 托管 | 轮询延迟受限于数据库与 poll interval；暂时没有 lease heartbeat | **选择** |

## Decision

1. `data_agent.dolphinscheduler_command_worker` 是复用 `DolphinSchedulerCommandConsumer.run_once` 的托管进程入口。它不直接调用 `start_workflow`、Run transition 或 success finalizer。
2. worker 按一个 command tenant 和一个 workload subject 运行；每个进程/Pod 必须配置跨副本唯一的 `DOLPHINSCHEDULER_COMMAND_WORKER_ID`。重复 worker ID 会削弱 stale-owner 隔离，部署 admission 或运维配置必须阻止重复使用。
3. 所有 provider 配置从严格环境合同读取。token 只能来自绝对路径的 `0600` 文件；safe summary、日志、health JSON 和异常包装不包含 token 或 provider payload。
4. lease 必须大于 provider HTTP request timeout；health max age 至少覆盖两个 poll interval。worker 只在当前批次结束后响应 SIGINT/SIGTERM，等待阶段使用可中断的 `Event.wait`，避免固定 sleep 阻塞 drain。
5. status JSON 采用临时文件写入后 `os.replace` 的原子投影，权限为 `0600`，状态包括进程 liveness、累计批次计数和脱敏错误 code。`starting/degraded/stopped` 或过期 status 返回 unhealthy；单个 command 的 terminal `failed` 是持久化业务投递结果，不自动把进程标为 dead，但通过 `failed_commands` 供告警消费。
6. worker 捕获 gateway availability failure 后写入 degraded 并继续轮询；未预期的编程异常停止进程，使进程管理器负责拉起并暴露故障。worker 不维护第二个 retry store，也不把 status 文件当作命令事实源。
7. 本 ADR 完成代码和本地验证，不宣称 staging/production 部署、真实 IAM/OIDC、provider callback、独立 DolphinScheduler metadata PostgreSQL 或故障恢复 SLO 已完成。

## Consequences

正面影响：

- API 线程与 provider command delivery 解耦，现有数据库 lease/claim 仍是唯一交付控制面；
- 进程收到终止信号可以可预测地 drain，status 可由进程管理器或探针读取；
- token、provider payload 和内部异常不会进入健康产物；
- worker 可以先以单体/受管进程部署，未来若吞吐证明需要 broker，consumer 合同仍可复用。

限制与缓解：

- 没有 lease heartbeat；provider timeout 变长前必须重新评估 lease 或增加受控 renew function；
- 轮询不是 push 唤醒，延迟由 poll interval 决定；先用 outbox backlog、claim latency 和 failure rate 验证是否达到 SLO；
- status 文件丢失或损坏只能导致 health fail closed，不能据此修改 command、Run 或 provider 状态；
- 唯一 worker ID 目前由部署配置保证，生产需要 admission/config validation 和重复 ID 告警。

## Verification

- worker 单元测试覆盖严格 env/config、token 文件权限、租约和 health 窗口、脱敏 status、gateway degraded、terminal command failure、信号 drain、可中断等待和失败关闭健康检查；
- gateway static validator 固定 worker class、consumer reuse、SIGTERM、interruptible wait、health evaluation 和 token-file markers，并拒绝 worker 直接拥有 provider/Run authority；
- `platform_truth` runtime inventory 登记 worker 的 owner、耐久性、状态权威和代码证据，环境访问指纹显式更新；
- staging/production 仍需补充真实 IAM/OIDC、唯一 worker ID、部署 status、lease 接管、重启 drain、callback 和告警 SLO 证据。

## Revisit Triggers

- backlog、claim latency、数据库锁竞争或 provider QPS 超过受管进程和 PostgreSQL 的 SLO；
- provider 调用时间接近或超过 lease，需要 heartbeat/renewal；
- 多区域、多数据库或网络隔离要求 broker/独立 service；
- 部署平台可以提供可靠的 identity/admission，使 worker ID 不再依赖人工配置；
- callback provider 提供签名事件或 OIDC federation，需要升级 ingress trust。
