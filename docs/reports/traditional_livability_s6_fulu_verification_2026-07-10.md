# 传统宜居性 S6 福禄镇超范围设施评估验证

## 验证结论

S6 已在璧山区福禄镇和平村、斑竹村真实规划样例上完成离线资源构建、点输入分析、规划地块输入分析、后端回归和前端生产构建。该能力是传统 GIS 语义与空间初筛，不是 UWM 预测，也不输出审批结论。

当前没有导入权威 LIV 2.0 43 类设施字典和权威设施相容性矩阵。因此真实运行只允许输出 `potential_conflict_review_required`、`no_screening_hit` 或 `insufficient_evidence`，不能输出正式冲突、正式相容、禁止建设或审批通过。

## 真实数据构建

构建命令：

```bash
/Users/zhouning/gisdataagent/.venv/bin/python \
  scripts/build_traditional_livability_s6_fulu.py \
  --source-root '/private/tmp/planning_sample_audit/规划院提供数据样例及Demo系统功能演示建议/01数据样例' \
  --facility-product /private/tmp/traditional_livability_phase1a_final2/uwm_traditional_livability_facility_product.json \
  --output /private/tmp/traditional_livability_s6_fulu_real
```

结果：

- 构建状态：`ready=true`，退出码 0；
- 规划资源：4,672 个；
- `source_record_id`：4,672 / 4,672 唯一；
- `resource_id`：4,672 / 4,672 唯一；
- 真实源图层反向重排后，资源 ID 保持一致；
- 范围内现状设施：7 个；
- 内部分类已映射设施：1 个；
- 未映射设施：6 个；
- 设施库存状态：`complete_inventory=false`；
- 和平村距离 CRS：CGCS2000 3 度带第 35 带投影，单位米；
- 斑竹村距离 CRS：EPSG:4523，单位米；
- 规划资源域包含村居住用地、村公共服务用地、村混合建设用地、村独立建设用地和显式 `unresolved`。

规划源状态未明确表达“预留”时，产品保持 `status_unknown`，没有根据地类名称猜测预留状态。

## 真实分析

### 地图点输入

- 和平村代表点：150 米范围命中 7 个规划资源；状态为 `potential_conflict_review_required`；
- 斑竹村代表点：当前加载快照中无空间命中；状态为 `no_screening_hit`；
- 两个结果均明确携带权威字典缺失、相容性矩阵缺失和设施库存不完整阻塞项；
- `no_screening_hit` 仅表示加载数据中未命中，不表示绝对无冲突。

### 规划地块输入

- 和平村测试地块 150 米范围命中 27 个规划资源；
- 斑竹村测试地块 150 米范围命中 23 个规划资源；
- 两个结果均为 `potential_conflict_review_required`；
- 无权威规则时没有产生 `confirmed_conflict` 或 `confirmed_compatible`。

单次真实分析约 0.13–0.18 秒。内核对地图 GeoJSON 设置 1,000 要素显示上限；完整命中证据行不截断，地图截断会显式报告总数、返回数和截断状态。

## 安全与证据边界

- 150 米是投影平面静态初筛阈值，不是法定退界、安全距离、网络距离或步行服务区；
- 空间邻近不自动等于业务冲突；
- `confirmed_conflict` 和 `confirmed_compatible` 必须引用适用的权威规则 ID；
- 前端人工确认必须由服务器根据当前请求、候选证据、字典版本和原始输入摘要重新验证；
- 未映射设施不会被静默丢弃；
- 采样设施库存限制无命中结论；
- 执行范围仅为和平村和斑竹村规划样例，不代表璧山区、重庆市或其他区域；
- 结果不是设施批准选址或规划审批意见。

## 自动验证

后端聚焦回归：

```text
234 passed in 11.56s
```

覆盖设施产品、权威字典、语义解析、两村资源适配、S6 空间内核、离线构建器、运行时 API、前端契约以及 S1/S7 回归。

前端生产构建：

```text
4106 modules transformed
build completed successfully
```

构建仅出现项目既有的 loaders.gl browser external 和 chunk 大小警告，没有 TypeScript 或 Vite 构建错误。
