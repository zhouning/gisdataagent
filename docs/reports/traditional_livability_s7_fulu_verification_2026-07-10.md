# 传统宜居性 S7 福禄镇小学选址验证报告

## 执行范围

本报告仅覆盖重庆市璧山区福禄镇的和平村、斑竹村两套村级规划样例。它不是重庆全域学校选址结果，也不是对需求文档中其他城市示例的执行结论。

## 方法

S7 使用传统 GIS 的确定性候选过滤和贪心 location-allocation：

- 需求：`JQDLTB` 中 `2121` 村居住/宅基地地块质心；面积作为**住宅用地面积代理**；
- 候选：`TDGHDL` 中村公共服务用地、村混合用地、其他独立建设用地；
- 距离：各村自身投影 CRS 内的平面欧氏距离，阈值 1,500 m；
- 排序：新增代理面积降序、重复覆盖面积升序、适宜性降序、候选面积降序、源地块 ID 升序；
- 供给：仅规划范围内的 `education.primary_school` POI 才能作为已核验本地供给；本次采样设施产品中没有定位到两村内的本地小学。

距离是 `projected_straight_line_distance_proxy`，不是道路网络距离、步行时间或道路网络可达性结果。

## 真实构建

命令：

```bash
python scripts/build_traditional_livability_s7_fulu.py \
  --source-root /private/tmp/planning_sample_audit/规划院提供数据样例及Demo系统功能演示建议/01数据样例 \
  --facility-product /private/tmp/traditional_livability_phase1a_final2/uwm_traditional_livability_facility_product.json \
  --output /private/tmp/traditional_livability_s7_fulu_real \
  --coverage-distance-m 1500 --max-sites 3
```

结果：

- 需求代理地块：643；总住宅用地面积代理：1,022,103.23 m²；
- 符合候选政策地块：29；被排除地块：2,428；
- 主要排除原因：耕地 1,302、园地 349、林地 189、道路 123、水体 70；
- 选出 3 个分析排序候选：斑竹村地块 `712`、和平村地块 `65599`、斑竹村地块 `1552`；
- 三轮后覆盖住宅用地面积代理：915,006.52 m²；未覆盖代理面积：107,096.71 m²；
- 上游设施产品为 POI 50,000 条采样 + 全 AOI，不是完整设施库存。

## 证据边界

1. `712`、`65599`、`1552` 仅为既定距离代理和候选政策下的分析排序，**不是批准建设学校的地块**。
2. 面积代理不是学生数、学龄人口、入学需求、班额或学校容量。
3. 未使用完整村级步行路网；输出不涉及分钟阈值或道路网络服务区。
4. 未使用学校容量、入学率、运营状态、权属、收储、DCR、BOQ、造价和资金数据。
5. 未提供权威 LIV 2.0 43 类字典或 FP/FPP 标准，结果不含设施合规判断。
6. 未做未来政策收益、长期影响或 UWM 优越性主张。

## 验证

- 适配器、供给分类、S7 引擎、构建器、API、既有传统宜居性与前端合同的聚焦测试通过；
- 前端 Vite 构建成功（4105 个模块）；
- Vite 报告项目既有大 chunk 提示，非 S7 TypeScript 编译错误。
