# ADR-121：资产分发授权锁定 DataProductVersion，并支持撤销与次数额度

**Status**: Accepted  
**Date**: 2026-08-02  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4.1

## Context

迁移 105 已把旧资产审批扩展为限时 `download` 授权，但授权仍只指向可变 Catalog 资产。审批后产品
继续发布新版本时，无法回答消费者获批的是哪个数据版本；管理员也不能撤销未过期授权，已生成 ZIP
继续通过通用用户文件地址访问。这些缺口会让“授权有效期”和“版本可追溯”只停留在界面文案。

现有系统已有两个权威边界：`agent_data_assets` 是当前 Catalog 资产事实源，`gda_control.data_product` /
`data_product_version` 是治理数据产品及不可变版本事实源。本轮不能引入第二套目录或审批表，也不能把
尚未实现的服务版本范围、独立 credential、服务速率/容量/成本 quota 和兼容性影响分析包装成完整
`ConsumerBinding`。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 只在申请记录保存版本字符串 | 改动最小 | 无外键、无法证明版本存在，容易成为展示字段 | 拒绝 |
| 新建平行资产到产品映射中心 | 关系结构化 | 产生第二个 metadata 写源和同步问题 | 拒绝 |
| Catalog 声明产品 URN，审批经注册表校验并快照精确版本 | 复用现有权威，授权可追溯，旧资产可兼容 | Catalog JSON 引用需在审批时校验 | **选择** |
| 立即实现完整 ConsumerBinding 与远端 Artifact 交付 | 目标最完整 | 同时引入 credential、quota、service range、provider 和对象分发，超出当前可验证边界 | 延后 |

## Decision

1. Catalog 资产只通过既有 `operational_metadata.publication.data_product_urn` 声明数据产品身份，不新增
   平行资产目录或映射表。
2. 管理员批准申请时锁定申请行并读取该声明；有声明时必须用申请管理员的租户调用治理产品注册表，
   解析当时 active 的不可变 `DataProductVersion`。引用无效、跨租户、注册表不可用或产品未发布时审批
   fail closed；没有声明的旧资产继续生成明确标识的 `asset_compatibility` 过渡授权。
3. 版本化授权在原 `agent_data_requests` 保存 tenant、Product URN、version UUID 和 version key，并以复合
   外键指向 `gda_control.data_product_version`。不创建第二套申请或审批 authority。
4. 授权状态继续保留原审批结果，撤销以 `revoked_at/by/reason` 表达；撤销原因必填，过期或已撤销授权
   不能再次撤销。打包和生命周期查询都以 `revoked_at IS NULL AND expires_at > NOW()` 判定活跃。
5. 每个新分发包登记独立 package 和 package-item 记录，关联产生它的授权；ZIP 内写入
   `_gda_distribution_manifest.json`，记录 consumer、资产、授权、到期时间和锁定产品版本。
6. 新包只返回 `/api/distribution-packages/{id}/download`。下载时重新校验 package、用户、到期时间以及
   所有关联授权；撤销同时使相关 package 失效并尽力删除平台生成的 ZIP。文件删除失败时数据库门禁仍
   拒绝下载，不能退回通用用户文件 URL。
7. package 和 item 表强制用户/管理员 RLS。内部文件路径只在服务端使用，不进入 API 响应。
8. 每次申请声明 1-100 次离线分发包额度，审批把申请额度固化为授权额度。普通用户打包时按稳定的
   asset ID 顺序锁定授权行，锁后重新统计关联该授权的 distinct package 数；达到额度时返回稳定的
   `quota_exhausted` 冲突，不创建文件或 package 记录。已撤销或失效包仍计入历史消耗，不能通过删除
   交付物重写额度审计；每次消耗前后值同时写入 ZIP manifest。

## Trade-offs

- 过渡资产仍可获批，保证旧目录可用，但界面和包清单必须显示“资产级过渡授权”，不能冒充版本化交付。
- 版本锁定证明审批合同指向哪个治理版本；当前 ZIP 内容仍来自 Catalog 本地文件路径，不等同于从该
  `DataProductVersion` 的远端 Artifact 重建。这一差异必须保留在 package manifest 的
  `delivery_source=catalog_asset_local_file` 中。
- 撤销采用当前申请表的兼容模型，没有把它命名为正式 `ConsumerBinding`。后续迁移必须保留 request、
  version、package 和撤销证据，不能重写历史。
- 当前 quota 只约束授权可生成多少个离线包，不代表 API/GIS Service 的 rate、容量、流量、成本或存储
  配额，也没有生成独立 consumer credential。

## Consequences

- 用户能看到授权锁定的产品版本；管理员能查看有效授权、填写原因撤销，并使既有包链接失效。
- 数据产品引用错误不会在审批后才暴露，跨租户产品不能被快照到申请。
- AR-4.1 仍缺 Product/Service version range、独立 credential、服务级 quota、promotion 前消费者影响分析、
  通知、正式 `ConsumerBinding` 聚合根，以及从远端 Artifact 按版本交付；AR-4 状态保持 `planned`。
- migration 106 必须由专用 migration authority 在明确环境中部署；本决策不授权修改共享开发数据库。

## Verification

- 数据分发、资产生命周期、产品注册表和 migration runner 定向测试通过。
- Ruff、前端 TypeScript/Vite 生产构建和 whitespace 检查通过。
- Catalog 桌面与移动端流程覆盖版本展示、管理员撤销、申请、审批、打包和受控下载链接。
- 一次性 PostgreSQL 16 环境连续应用 migration 105-107，并以两个并发打包事务验证最后一次额度只能
  被一个请求消费；另一个请求锁后观察到最新 package 计数并 fail closed。

## Revisit Triggers

- 首个 Catalog 资产改为直接投影治理 `DataProductVersion` Artifact，而不是本地文件路径；
- 引入 API/GIS Service version range、credential rotation 或服务级 rate/capacity/cost quota；
- promotion 需要在切换 active pointer 前分析并通知受影响消费者；
- 迁移到正式 `ConsumerBinding` authority 时，用 request/version/package 外键和事件迁移保留本 ADR 证据。
