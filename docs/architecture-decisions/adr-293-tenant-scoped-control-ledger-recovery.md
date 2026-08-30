# ADR-293: Tenant-Scoped Control Ledger Recovery Evidence

状态：已采纳，合同、单测和 disposable PostGIS 认证已实现；不是生产 DR 退出门  
日期：2026-08-25

## 背景

现有恢复演练能比较数据库的全局逻辑状态，但不能证明恢复后每个租户仍只看到自己的
Resource、Run、Artifact、QualityResult 和 Lineage。只比较总行数会漏掉租户串行、跨租户
外键引用和恢复后的幂等重放问题。AR-1/AR-2 的退出门因此仍需要一条明确的控制账本
双租户恢复证据。

## 决策

新增 `data_agent.platform_runtime.tenant_recovery` 合同：

- 对每个租户、每张控制账本表计算排序无关的行投影 SHA-256 和行数；
- 把租户列表、表摘要和 manifest fingerprint 固化为 `gda.tenant_recovery_manifest.v1`；
- 恢复后要求 source/restored manifest 完全相等；
- 通过 `gda_control_gateway` + transaction-local `app.current_tenant` 逐租户读取，要求每张表
  只返回当前租户的预期行数；
- 以跨租户 ResourceVersion predecessor 和跨租户 Gateway read 作为负向探针；
- 重放已存在 Resource 必须返回 `created=false`，不能生成第二套身份或账本行。

认证脚本 `scripts/certify_tenant_scoped_recovery.py` 使用固定
`postgis/postgis:16-3.4` 容器，创建两个租户的 definition、source/output ResourceVersion、
PlatformRun、provider observation、Artifact、QualityResult 和 LineageEvent，执行 custom-format
`pg_dump`，恢复到同容器内的新数据库，重新应用数据库级 gateway grant，再通过 Gateway/RLS
完成恢复后检查。容器、数据库和 dump 在 finally 中清理。

## 取舍与边界

manifest 只保存控制账本的非敏感行投影，不把数据库内容或凭据复制到报告；排序和时间/UUID
规范化保证 SQL 返回顺序与物理恢复布局不改变身份。该切片证明控制账本的租户边界和恢复后
幂等性，不外推到 OpenMetadata、Gravitino、DolphinScheduler、MinIO 对象字节、跨 store PITR、
备份加密、异地复制、生产 HA 或批准的 RPO/RTO。

## 已验证范围

`data_agent/test_tenant_recovery.py` 的 4 个合同测试通过。2026-08-25 disposable 认证通过：

- 两个租户、9 张控制账本表的 source/restored manifest 完全相等，manifest SHA-256 为
  `0f1e127134e3f02b6679222b95bc204c0bbf880461d6e1acbf62e33e2688fd53`；
- 两个租户各自可见全部预期行，跨租户可见行均为 `0`；
- 跨租户 Gateway read 返回 not found，跨租户 ResourceVersion predecessor 被拒绝；
- source 和 restored 的重复 Resource 登记均返回 `created=false`；
- pg_dump 85261 bytes，dump SHA-256 为
  `7e5d8174ac47acf8c8612ddb3573353ee670df4d2cc2ada18ba8d0d0d92883df`；
- 报告 `.tmp/tenant-recovery/acceptance-report.json`，文件 SHA-256 为
  `c4aebfda5059299a103d0c8c8cf0121d6c4a35a1eabbbe8cc923fc5de02e3803`。

本证据把“控制账本双租户恢复”从未验证推进为已验证切片，但 AR-1、AR-2 总体仍为
`in_progress`。
