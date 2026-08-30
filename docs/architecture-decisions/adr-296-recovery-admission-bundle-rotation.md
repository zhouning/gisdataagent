# ADR-296: Recovery Admission Bundle Canonicalization and Rotation

状态：已采纳，严格解析、规范化序列化和原子文件轮换已实现；环境签发、OIDC 身份和生产 Secret 分发仍未完成  
日期：2026-08-25

## 背景

`ProjectionRecoveryControllerAdmissionBundleResolver` 已经要求 worker 使用按
`plan_sha256` 索引的 server-owned admission evidence，但此前 bundle 只是调用方约定的 JSON。
字段多写、租户副本顺序错误、半写文件或轮换时的瞬间空文件，都可能让部署行为依赖具体脚本。

## 决策

新增 `data_agent.platform_runtime.cross_store_recovery_admission_bundle`，冻结
`gda.cross_store_recovery_admission_bundle.v1`：

- 顶层只能有 `schema_id` 和 `admissions`；entry 只能有 binding、完整的
  `persisted_tenant_ids` 和显式的 `object_version_id_remap_allowed`。
- 每个 key 必须是小写 plan SHA-256；binding 重新按 `CrossStoreRecoveryBinding` 校验，tenant
  副本必须与 binding 的排序租户集合完全一致。
- `ProjectionRecoveryAdmissionBundle.from_admissions(...)` 生成排序稳定的 canonical JSON；不接收
  provider endpoint、credential、row bundle 或其他运行时目标。
- `rotate_projection_recovery_admission_bundle(...)` 在同一目录写入临时文件、fsync、设置 `0440`
  权限后 `os.replace`；worker 每次 claim 读取并解析完整文件，不会看到半写内容。
- source ResourceVersion/content SHA-256 与 sealed plan 的精确绑定仍由 runtime resolver 执行；bundle
  canonicalization 不替代 controller admission 或 durable authority。

## 运行边界

环境-owned recovery controller 先完成 source/restored manifest 对账和 PostgreSQL durable
read-back，再调用 `from_admissions` 生成 bundle，最后原子轮换 Secret/挂载文件。撤销或替换证据时，
先停止/缩容 worker，再轮换 bundle 并重新 admission；删除 bundle 会使新 claim fail closed。

部署入口分为两层：`k8s/optional/projection-recovery-worker` 是默认 `replicas: 0` 的安全 profile，
`k8s/overlays/projection-recovery-sandbox` 只在环境审核后把该 Deployment patch 到 `replicas: 1`。
overlay 不复制 base Secret，也不改变 NetworkPolicy、ServiceAccount 或容器安全上下文。

该文件格式和 `0440` 权限不提供签名或来源认证。生产部署仍需 workload identity/OIDC、Secret
manager、审计化签发/轮换、HA controller、provider replication/PITR 和 RPO/RTO 验收；本 ADR 不把
本地文件存在升级为生产安全能力。

## 已验证范围

聚焦回归覆盖 canonical round-trip、严格未知字段拒绝、tenant-copy 漂移拒绝、plan key 拒绝、原子
轮换无临时残留、缺失 plan fail closed 和无凭据输出；与既有 runtime resolver 联合回归通过。
