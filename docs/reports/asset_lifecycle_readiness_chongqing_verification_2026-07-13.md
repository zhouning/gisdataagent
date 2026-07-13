# 重庆资产目录与生命周期就绪度验证报告（需求5）

## 结论

- 已形成 `uwm.asset_lifecycle_readiness.v1` 跨产品资产目录与生命周期数据契约产品。
- Bundle：`asset-lifecycle-a03ef87f9198c1fbd837`。
- 引用 6 类已验证产品：基础设施、公共服务、公共空间、文化场所、商业活动与数字平台能力。
- 所有来源数量保持各自记录语义，不求和为唯一资产数量；`unique_asset_count=null`。
- 16 个生命周期证据通道全部为 `unavailable`，未把缺失维护记录解释为良好状态。
- UWM 的实体消歧、资产状态物化、退化、故障转移、维护响应、依赖传播、替换、恢复与未来 rollout 全部关闭。

## 可支持的最大声明

`cross_product_asset_catalog_lifecycle_contract_and_uwm_asset_state_readiness`

该产品可用于发现现有空间资产相关数据产品、定义后续权威资产主数据与生命周期事件接入合同，并明确 UWM Kernel 的开放条件；不能用于声明资产权属、容量、状态、健康度、维护绩效、故障概率、剩余寿命、成本、替换优先级或恢复时间。

## 生产阻塞项

- 权威且稳定的资产 ID 与跨源实体映射缺失。
- 权属、托管方、运营方、投运日期及生命周期状态缺失。
- 巡检、状态、维护工单、故障、维修、更换和退役事件缺失。
- 容量、服务角色、估值、成本与资产依赖关系缺失。
- UWM 生命周期状态与退化/恢复 Kernel 缺乏可校准的时间序列。

## 验证命令

`python scripts/verify_asset_lifecycle_readiness_chongqing.py data/uwm_public_proxy/chongqing_central/asset_lifecycle_readiness_chongqing`
