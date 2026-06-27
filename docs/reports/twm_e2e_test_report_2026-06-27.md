# TWM 自然资源部演示端到端测试报告

测试日期：2026-06-27
测试对象：GIS Data Agent 中的 TWM 原型演示流程
对齐脚本：`docs/reports/twm_natural_resources_demo_script_2026-06-27.md`
测试入口：`http://127.0.0.1:8000/`

## 1. 本次重测原因

前一轮测试存在明显漏洞：只验证了 TWM 页面流程、接口响应和 UI 状态，没有验证“总览地图”里的演示空间范围是否与“数据证据”里的数据基础空间范围一致。因此即使端到端流程通过，也可能出现地图叙事和数据基础空间位置不对应的问题。

本次重测已把空间一致性纳入自动化测试：全量数据加载、定位审查区、风险命中、推荐方案四个地图联动状态，都必须与主演示数据包 `twm_bishan_multi_admin_eval` 的空间 bbox 相交。

## 2. 最新数据基础

| 数据包 | 用途 | 空间要素数 | 空间 bbox | 本次演示结论 |
|---|---:|---:|---|---|
| `twm_bishan_multi_admin_eval` | 主演示数据包，多行政单元评估样例 | 21,603 | `[106.152182211, 29.667518609, 106.367539714, 29.886844144]` | 总览地图、全量加载、风险命中和推荐方案均对齐此范围 |
| `twm_bishan_demo` | 工程原型与回归测试样例 | 5,067 | `[106.248282100, 29.772909093, 106.367765131, 29.886844144]` | 与主范围高度重叠，但不是本次默认叙事样例 |
| `twm_one_map_village_standard_sample` | 一张图村庄规划标准结构样例 | 5,439 | 投影坐标量级，例如 `[35607712.850, 3274292.142, 35612624.426, 3281180.232]` | 当前不能直接作为 WGS84 地图叠加演示对象 |

`twm_bishan_multi_admin_eval` 的数据总量为 22,401 条，其中空间 GeoJSON 全量为 21,603 个要素，表格和审查记录构成其余数据基础。

## 3. 测试用例矩阵

| 用例 ID | 对齐演示脚本章节 | 自动化操作 | 核心断言 | 结果 |
|---|---|---|---|---|
| TC-00 | 演示前准备 | 注册/登录，打开 `智能分析 -> TWM` | 标题为 `国土空间世界模型`；子 tab 包含 `总览地图`、`数据证据`、`操作推演`、`技术载荷` | 通过 |
| TC-01 | 一、总览地图 | 点击 `定位审查区` | 状态为 `已联动：审查区定位`；地图 bbox 与 `twm_bishan_multi_admin_eval` bbox 相交 | 通过 |
| TC-02 | 一、数据证据 | 选择 `璧山多行政单元评估样例`，查看空间目录，点击 `synthetic_projects.geojson` 的 `上图`，再点击 `全量加载空间数据`，隐藏/显示 `parcel_current.geojson` | 页面显示 `空间图层目录`、`parcel_current.geojson`、`可直接叠加`、字段摘要、`XMMC` 和样例属性；单图层请求包含 `layer=synthetic_projects.geojson`，接口只返回 1 个图层和 90 个要素；全量请求包含 `max_features_per_layer=all`；接口为 `full_geojson`；坐标诊断为 `ready`；隐藏图层后地图推送图层数从 6 变为 5，恢复显示后回到 6；单图层和全量加载 bbox 均与主演示 bbox 相交 | 通过 |
| TC-03 | 六、数据证据 | 查看数据基础浏览器和详细证据区 | 显示 `22,401`、空间图层目录、完整数据清单、完整验证快照、问题-数据适配、来源报告、`twm_data_foundation_health.md` | 通过 |
| TC-04 | 二、操作推演 | 点击 `璧山演示`，创建项目，点击 `构建状态` | 项目创建成功；状态版本存在；对象数和关系数均大于 100 | 通过 |
| TC-05 | 三、规则审查 | 点击 `检查业务规则`，切回总览地图 | 规则命中数和证据项数大于 0；状态为 `已联动：风险命中`；风险图层 bbox 与主演示 bbox 相交 | 通过 |
| TC-06 | 四、风险预测与验证 | 点击 `风险预测`、`验证口径`、`证据审计` | 风险预测返回约束风险/forecast；验证口径返回 claim ladder 或 stages；审计证据数大于 0 | 通过 |
| TC-07 | 五、方案比选 | 点击 `载入候选`、`方案比选`，切回总览地图 | 候选方案数大于 0；有选中候选；状态为 `已联动：推荐方案`；方案图层 bbox 与主演示 bbox 相交 | 通过 |
| TC-08 | 六、数据证据 | 点击 `基线对比` | 返回 metric comparisons；页面出现 `TWM` 或 `基线` 对比内容 | 通过 |
| TC-09 | 七、技术载荷 | 切换到 `技术载荷`，展开 `最新技术载荷` | JSON 面板展开，且载荷区域显示结构化 JSON 内容 | 通过 |
| TC-10 | 全流程质量门 | 全流程监听 console/page errors | 无未忽略的 page error；无未忽略的 console error | 通过 |

## 4. 自动化测试证据

后端数据基础测试：

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py::test_data_foundation_assessment_states_current_data_boundary \
  data_agent/test_territory_world_model.py::test_data_foundation_map_preview_returns_sampled_geojson_layers \
  data_agent/test_territory_world_model.py::test_data_foundation_map_preview_reports_wgs84_overlay_readiness \
  data_agent/test_territory_world_model.py::test_data_foundation_map_preview_blocks_projected_coordinate_layers \
  data_agent/test_territory_world_model.py::test_data_foundation_map_preview_accepts_full_geojson_layers \
  data_agent/test_territory_world_model.py::test_data_foundation_map_preview_filters_to_requested_layer \
  data_agent/test_territory_world_model.py::test_data_foundation_map_preview_route_returns_layers \
  data_agent/test_territory_world_model.py::test_data_foundation_map_preview_route_accepts_all_query \
  data_agent/test_territory_world_model.py::test_data_foundation_map_preview_route_accepts_layer_query -q
```

最新 focused 结果：`9 passed in 32.13s`，覆盖数据基础空间图层目录、属性字段目录、map preview、WGS84 可叠加诊断、投影坐标阻断诊断、全量加载和单图层 `layer=` route 查询参数。

前端构建：

```bash
npm --prefix frontend run build
```

结果：构建成功。Vite 输出仍有既有 chunk size 和 loaders.gl browser external 警告，但未阻断构建。

容器健康检查：

```bash
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/
```

结果：`200`

完整端到端测试：

```bash
npx playwright test tests/e2e/specs/twm_demo_workflow.spec.ts \
  --config tests/e2e/playwright.mmfe.config.ts \
  --project chromium
```

最新结果：`1 passed (3.9m)`

## 5. 截图证据

| 截图 | 对齐测试用例 | 文件 |
|---|---|---|
| 空间图层目录逐层上图 | TC-02 | `tests/e2e/screenshots/twm_spatial_catalog.png` |
| 全量空间数据加载 | TC-02 | `tests/e2e/screenshots/twm_data_browser.png` |
| 数据证据详细清单 | TC-03 | `tests/e2e/screenshots/twm_data_evidence.png` |
| 总览地图定位审查区 | TC-01 | `tests/e2e/screenshots/twm_overview_locate.png` |
| 总览地图风险命中 | TC-05 | `tests/e2e/screenshots/twm_overview_risk.png` |
| 总览地图推荐方案 | TC-07 | `tests/e2e/screenshots/twm_overview_plan.png` |
| 技术载荷 | TC-09 | `tests/e2e/screenshots/twm_payload.png` |
| 全流程最终状态 | TC-00 至 TC-10 | `tests/e2e/screenshots/twm_demo_workflow.png` |

## 6. 本次新增的防回归检查

1. 数据基础全量加载必须请求 `max_features_per_layer=all`。
2. 全量加载结果必须是 `delivery_mode = full_geojson`。
3. 全量加载的预览要素数必须等于源空间要素数。
4. 数据基础浏览器必须在全量加载前显示空间图层目录和图层级坐标状态。
5. 空间图层目录必须显示字段摘要、代表性字段 `XMMC` 和样例属性，不能只显示几何范围。
6. 单图层 `上图` 必须请求 `layer=synthetic_projects.geojson`，且接口只返回该图层。
7. 单图层 `上图` 的源要素数和预览要素数必须均为 `90`。
8. 全量加载后图层开关必须能隐藏 `parcel_current.geojson`，地图推送图层数从 6 变为 5。
9. 图层开关必须能重新显示 `parcel_current.geojson`，地图推送图层数恢复为 6。
10. 主演示包全量加载必须返回 `map_overlay_readiness.status = ready`。
11. 主演示包所有空间图层的 `crs_diagnostic.map_overlay_ready` 必须为 `true`。
12. 投影坐标样例必须返回 `requires_crs_conversion`，不能被当成 WGS84 演示图层直接叠加。
13. 单图层上图和全量数据加载后的地图 bbox 必须与 `twm_bishan_multi_admin_eval` bbox 相交。
14. `定位审查区` 地图 bbox 必须与 `twm_bishan_multi_admin_eval` bbox 相交。
15. `风险命中` 地图 bbox 必须与 `twm_bishan_multi_admin_eval` bbox 相交。
16. `推荐方案` 地图 bbox 必须与 `twm_bishan_multi_admin_eval` bbox 相交。
17. 技术载荷 tab 必须可打开、可展开，并显示结构化 JSON 内容。

## 7. 仍需明确的边界

1. 当前所有治理对象、审查记录、规则命中和方案数据仍是演示/非生产数据，不能包装成权威结论。
2. `twm_one_map_village_standard_sample` 当前坐标不是 WGS84 经纬度，不应在同一地图演示里和主演示样例混讲。
3. 本次 E2E 验证的是演示链路和空间一致性，不等于验证真实业务增益。真实增益仍需要接入自然资源部门权威边界、审批历史、政策动作历史和人工/规则/优化基线。

## 8. 测试结论

基于最新数据基础，TWM 演示脚本中的准备、总览地图、操作推演、规则审查、风险预测、证据审计、方案比选、数据证据、基线对比和技术载荷步骤均已完成自动化端到端验证。

本次已经修复并验证之前遗漏的关键问题：地图联动不再只检查“状态文字是否变化”，而是检查实际推送给地图的 GeoJSON 空间范围是否与主演示数据包对应；同时新增坐标诊断和空间图层逐层上图验证，避免投影坐标样例被误当成 WGS84 经纬度图层直接叠加，也避免全量加载掩盖单个图层不可用的问题。
