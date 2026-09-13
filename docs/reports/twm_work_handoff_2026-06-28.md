# TWM 工作交接记录

日期：2026-06-28
分支：`feat/v12-extensible-platform`
目标：保存自然资源部原型演示前的 TWM 数据基础、地图交互、演示脚本和端到端验证状态，便于新窗口继续工作。

## 当前已完成

1. TWM 前端中文优先，并按 `总览地图`、`数据证据`、`操作推演`、`技术载荷` 拆分子 tab。
2. `数据证据` 页默认使用 `twm_bishan_multi_admin_eval` 主演示数据包。
3. 空间图层目录展示图层名称、要素数、bbox、CRS 诊断、字段数量、代表性字段和样例属性。
4. `synthetic_projects.geojson` 支持逐层 `上图`，接口通过 `layer=synthetic_projects.geojson` 只返回该图层。
5. `全量加载空间数据` 返回 6 个空间图层、21,603 个空间要素，并联动中间地图。
6. 全量加载后的 `坐标诊断` 图层列表支持逐图层 `隐藏/显示`，可用于演示时聚焦查看。
7. 投影坐标样例 `twm_one_map_village_standard_sample` 会被 CRS 诊断阻断，不直接叠加到 WGS84 地图。
8. 总览地图的 `定位审查区`、`风险命中`、`推荐方案` 已与主演示 bbox 对齐。

主演示 bbox：

```text
[106.152182211, 29.667518609, 106.367539714, 29.886844144]
```

## 最新验证记录

前端构建：

```bash
npm --prefix frontend run build
```

结果：通过；仍有既有 Vite chunk size 和 loaders.gl browser external 警告。

后端数据基础聚焦测试：

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

结果：`9 passed in 32.13s`

本地容器健康检查：

```bash
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/
```

结果：`200`

完整 TWM 演示 E2E：

```bash
npx playwright test tests/e2e/specs/twm_demo_workflow.spec.ts \
  --config tests/e2e/playwright.mmfe.config.ts \
  --project chromium
```

结果：`1 passed (3.9m)`

## 关键文件

- `data_agent/territory_world_model/service.py`
- `data_agent/api/territory_world_model_routes.py`
- `data_agent/test_territory_world_model.py`
- `frontend/src/components/datapanel/TerritoryWorldModelTab.tsx`
- `frontend/src/styles/layout.css`
- `tests/e2e/specs/twm_demo_workflow.spec.ts`
- `docs/reports/twm_natural_resources_demo_script_2026-06-27.md`
- `docs/reports/twm_e2e_test_report_2026-06-27.md`
- `docs/reports/twm_iteration_improvement_plan_2026-06-27.md`
- `docs/reports/twm_geospatial_world_model_theoretical_innovation_2026-06-27.md`
- `docs/reports/twm_national_authoritative_data_potential_2026-06-27.md`
- `docs/roadmap.md`

## 新窗口接续建议

1. 先打开 `docs/reports/twm_natural_resources_demo_script_2026-06-27.md`，按脚本手工走一遍演示。
2. 如果要继续增强地图演示，优先做“单图层聚焦模式”或“图层透明度/顺序控制”，不要再扩大理论声明。
3. 如果要继续增强数据基础说明，优先补“表格字段浏览”和“图层-表格证据关联”，避免只做 UI 装饰。
4. 继续保持边界：当前数据仍为演示/非生产数据，不能作为自然资源部门权威审批结论。
