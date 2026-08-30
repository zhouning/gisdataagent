# ADR-292: JQDLTB Layered Candidate to DataProductVersion Release Gate

状态：已采纳，合同、数据库强制门和 disposable PostGIS 认证已实现；尚无真实发布  
日期：2026-08-25

## 背景

JQDLTB transformation 已能在批准后生成 Raw、ODS、DIM、DWD、ADS、quarantine、质量和血缘候选，
但执行器有意不创建 `DataProductVersion`。之前缺少的是候选与既有产品 registry 之间的明确发布门：
哪些对象必须属于同一 Run、哪些业务和运行责任必须已批准、发布 ApprovalCase 应绑定哪些内容，以及
什么情况下才允许调用现有 `DataProductRegistry.publish`。

另一个实现问题是：transformation 的平台 `OUTPUT Artifact` 指向 ADS JSON，`content_sha256` 却是完整
layer manifest 的指纹。URI 指向的字节与登记的内容身份不同，不适合作为发布分发物。

## 决策

新增 `JqdltbDataProductReleasePlan`。发布计划必须同时绑定：

- 一个 `succeeded` 的 DataOps `PlatformRun` 及其 immutable source binding；
- 已批准的 executable JQDLTB transformation contract；
- completed 且 quality passed 的 transformation result；
- 同一 Run 和 output `ResourceVersion` 的 layer-manifest Artifact、`QualityResult`、质量 evidence Artifact 和 source-to-output lineage；
- Raw、ODS、DIM、DWD、ADS、quarantine 六层的记录数、相对路径和内容指纹；
- business steward、license、DataSLO、ServiceSLO、on-call、environment owner、DeploymentProfile 和 backup/restore evidence；
- 独立的 `data_product.publish_jqdltb` ApprovalCase；
- 完整 `DataProductVersion` manifest 和发布计划 SHA-256。

任何治理字段包含 `pending`、`unknown`、`unassigned`、`tbd` 或 `todo` 时，发布计划构造直接失败。
发布时重新读取 ApprovalCase authority，要求 case 为 approved、未过期、计划指纹和完整 request context
完全一致，然后才调用现有 `DataProductRegistry.publish`。该实现不建立第二套产品 registry 或产品状态机。

数据库增加 `jqdltb_data_product_release` 不可变绑定。`DataProductRegistry.publish` 在同一事务内校验
Run、Artifact、QualityResult、LineageEvent、transformation ApprovalCase、release ApprovalCase 和
operating contract，再写 `DataProductVersion` 与 release binding。deferred constraint trigger 在事务提交前
检查 JQDLTB mapping contract 必须存在完全一致的 release binding；直接调用 registry 而不提供发布计划时，
即使绕过 service，也会整笔回滚。该表强制 RLS，gateway 只有 SELECT/INSERT 权限，不能 UPDATE/DELETE。

transformation executor 同时新增 `layer-manifest.json`。平台 `OUTPUT Artifact` 现在指向该文件，其 URI、
size 和 `content_sha256` 对应同一组字节；ADS JSON 继续作为 manifest 中的 serving layer member，而不冒充
整个分层 bundle。

## 取舍

只在 release service 校验改动最少，但调用方可以直接进入 registry，不能形成平台强制门。另建一套
JQDLTB product registry 会复制产品状态和晋级逻辑。当前方案保留一个 registry，用 deferred trigger
允许 `DataProductVersion` 与 release binding 在同一事务内写入，并在 commit 前统一核验。代价是 registry
与 `230_jqdltb_data_product_release_authority.sql` 必须同步演进，数据库验收也必须加载当前 promotion 相关迁移；
认证脚本已把这组依赖固化。

## 已验证范围

聚焦回归覆盖：

- 同一 Run/source/output、六层 manifest、quality、lineage 和 operating contract 的成功编译；
- pending business steward 的拒绝；
- ADS 记录数或 layer manifest 篡改的拒绝；
- release plan SHA-256 篡改的拒绝；
- pending release ApprovalCase 的拒绝；
- ApprovalCase request context 漂移的拒绝；
- approved case 后只通过既有 registry 发布；
- transformation candidate 的原子输出、replay 和 evidence failure recovery。

2026-08-25 的 JQDLTB 聚焦回归为 `28 passed`，registry 相关回归为 `56 passed`。

同日通过 `scripts/certify_jqdltb_data_product_release.py` 在全新
`postgis/postgis:16-3.4` 容器完成 `1 passed` 数据库认证。认证库最终只有 1 个 succeeded Run、
3 个 Artifact、1 个 passed QualityResult、1 条 LineageEvent、2 个不同 action 的 approved
ApprovalCase、1 个 DataProductVersion、1 个 release binding 和 1 条产品事件。pending 审批被拒绝，
直接 registry 绕过在提交时回滚，批准后的发布和幂等重放通过；deferred trigger、RLS/FORCE RLS、
不可变触发器和 gateway append-only 权限均由数据库读取确认。两条并发 publish 请求也已执行验证：
只有一个请求创建版本/binding/event，另一个请求收敛为幂等 replay。

本次报告位于 `.tmp/jqdltb-data-product-release/acceptance-report.json`，SHA-256 为
`3a4d60945a43be1cca5e272f8140a6b3da0948b583e9009df9997fa801cf7e6e`。报告明确标记
`production_claim=false`、`real_business_approval_claim=false`；容器内审批和产品版本是合同认证 fixture，
随 disposable 容器销毁，不能作为真实 JQDLTB 发布记录。

## 尚未完成

- 业务方尚未提供真实 transformation 策略、business steward、license 和 SLO/on-call 批准；
- 尚未对冻结的 1,555 条 JQDLTB 执行 approved contract 和 source-quality 重跑；
- 尚未产生同一真实 Run 的 Raw→ADS 平台 evidence graph；
- 尚未创建 JQDLTB `DataProductVersion`，也没有 PostGIS serving、MVT/Features、SLO、Incident 和 rollback 对账；
- 当前认证未覆盖双租户/跨角色以外的生产数据库升级/恢复；并发发布争用、RLS/不可变更新和 gateway 权限已由执行级负向探针验证。

因此 AR-0 至 AR-4 状态均保持 `in_progress`。
