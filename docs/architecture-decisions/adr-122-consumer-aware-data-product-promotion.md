# ADR-122：DataProduct 前向切换必须确认最新消费者影响

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-3、AR-4.1

## Context

迁移 106-107 已让过渡分发授权锁定精确 `DataProductVersion`，并具有撤销、到期和离线包次数额度。
但发布新版本仍会立即移动 active pointer，平台无法在切换前回答“谁仍在使用旧版本、还剩多少交付
额度”，也无法证明操作员确认的是切换当时的最新名单。

本轮不能新建平行消费者目录。正式 `ConsumerBinding` 尚未具备 Product/Service version range、独立
credential、服务级 quota、兼容性合同和通知，因此已有版本锁定分发授权只能作为过渡消费者证据。

## Decision

1. 新 `DataProductVersion` 继续以不可变记录发布。若当前 active 版本没有有效分发授权，发布可直接
   `advanced`；若存在有效授权，新版本只记录为 `staged`，不得改变 active pointer。
2. 新增租户隔离的 `active_distribution_grant_impact` 数据库函数，只向控制面网关返回指定产品版本的
   有效授权、consumer、asset、到期时间、锁定版本、批准额度、已用和剩余额度。网关不获得申请表的
   跨租户直接读取能力。
3. 影响预览按稳定顺序生成规范化证据和 SHA-256 指纹。前向 promotion 必须在同一事务中重新计算影响；
   有消费者时，仅接受与最新证据完全一致的 `impact_acknowledgement`。名单或额度证据变化后，旧指纹
   fail closed，并返回最新影响供操作员重新确认。
4. 产品发布、前向 promotion 和产品版本分发审批共用
   `data-product-promotion:{tenant_id}:{product_urn}` PostgreSQL advisory transaction lock。由此保证新授权
   不会在影响计算与 active pointer 切换之间插入并逃逸确认。
5. staged 和 promoted 事件分别引用独立、不可变的影响快照。快照记录 from/to version、指纹、consumer
   计数、授权明细、剩余额度、评估者、评估时间和确认模式；数据库触发器拒绝 UPDATE/DELETE。
6. staged 发布使用同一 idempotency key 重试时返回第一次保存的影响证据，不重复创建版本、事件或
   快照，也不把后来变化的影响名单冒充第一次操作结果。最新名单始终由 preview 或 promotion 冲突响应
   提供。

## Trade-offs

- 影响指纹精确覆盖当前有效过渡授权和离线包额度，操作员确认可审计；但它不是正式消费合同或自动迁移
  计划。
- advisory lock 把授权批准和版本切换串行化，牺牲同一产品上的少量并发度，换取不会漏掉新消费者。
- 已发布但 staged 的版本可以被查询和审计，只有 active pointer 的默认读取与交付语义保持旧版本。
- 紧急 rollback 保留既有 ancestor 校验与审计路径，当前不要求影响确认。该例外必须在正式
  `ConsumerBinding` 和事故流程落地时重新评审。

## Consequences

- 操作员在前向切换前能看到仍使用旧版本的用户及其剩余额度；影响变化后旧确认自动失效。
- staged、确认和最终切换形成不可变审计链，重复请求不会产生重复事实。
- 当前没有消费者通知、兼容性判定、迁移计划、Product/Service version range、credential rotation、
  服务级 rate/capacity/cost quota 或正式 `ConsumerBinding` authority。AR-4.1 与 AR-4 状态保持不变。
- migration 108 只能由专用 migration authority 在明确环境部署；本决策不授权迁移共享开发数据库。

## Verification

- 产品注册表与分发定向测试覆盖稳定指纹、无消费者路径、API preview、陈旧确认和共享锁合同。
- `scripts/certify_data_product_promotion_impact.py` 在自动清理的一次性 PostgreSQL 16 中验证：v1 active、
  v2 staged、staged 重试幂等、新授权改变指纹、旧确认被拒、最新确认切换 v2、事件引用影响证据、证据
  不可修改以及跨租户函数和表均返回零行。
- Ruff、whitespace 和相关 Catalog/Auth/Migration 回归必须通过。

## Revisit Triggers

- 正式 `ConsumerBinding` authority 和版本兼容性合同落地；
- 增加消费者通知、迁移期限、deprecation 或强制下线流程；
- rollback 需要纳入消费者影响确认和事故豁免审计；
- 服务级 credential、流量/成本 quota 或 `ServiceDeploymentRevision` 进入 promotion 门。
