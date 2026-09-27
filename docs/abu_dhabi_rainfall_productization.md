# 阿布扎比 / 阿联酋雨型产品化实施说明

## 结论边界

当前工程仓库已登记并可审计使用的是 **Abu Dhabi 2022 官方 Zone B DDF Table 3-6**。该表提供 2、5、10、25、50、100 年一遇的累计雨量/强度表，但没有直接给出完整的时间雨型；5 分钟嵌套 DDF 插值、交替块排序和峰值位置属于显式建模假设。

“Zone A 为东部山区、Zone B 为沿海/阿布扎比城市”目前作为产品的气候分区配置保留，但项目资料中尚未登记 Zone A 权威 IDF/DDF 数值。因此系统不会根据 Zone A 自动编造重现期设计暴雨；Zone A 可以运行客户自定义序列或用户明确给定总量的模板雨型，但该结果不具有官方 Zone A 设计暴雨证据等级。

## 已实现的产品能力

- 独立雨型契约：`gwm.abu_dhabi_rainfall_profile.v1`。
- 分区目录：`zone_a`（待权威数据）和 `zone_b`（Zone B DDF 已登记）。
- 时间雨型模板：均匀、前峰、后峰、中央峰、双峰、交替块、官方 Zone B DDF、人工/导入序列。
- 人工时序：以 mm/时间步输入，校验非负、时长、步长和累计总量，适配 SWMM 的 mm/h。
- 空间模式：`uniform`、`zones`、`raster`（栅格模式保留但当前拒绝运行，避免伪装成已接入）。
- GeoJSON 分区：每个分区可设置 `rainfall_factor`、优先级和独立时间雨型 ID；输入坐标默认 EPSG:4326，二维运行时转换到 EPSG:32640。
- 地图联动：通用 Leaflet Draw 完成多边形/矩形后发布 `abu-rainfall-zone-drawn` 事件，雨型面板自动接收 GeoJSON 并纳入下一次运行请求。
- 方案生命周期：雨型面板可将当前草稿保存到私有雨型目录，并按方案 ID 加载；保存同时生成标准化 `profile.json` 和 `rainfall.csv` 快照，返回 SHA-256 哈希、来源、总量、时长和步长。
- 方案管理安全边界：下拉框“选中”不等于已加载；只有先加载当前方案，才允许“覆盖已加载方案”。覆盖请求携带已加载快照的 SHA-256，服务端发现其他客户端已更新时返回 `409 rainfall_profile_conflict`，避免静默覆盖。
- 方案状态清理：人工设计、模板设计、官方 Zone B 设计、降雨来源切换、CSV 导入和恢复默认都会解除旧方案绑定；已删除或被其他会话删除的方案在刷新列表后自动解除绑定。修改后的草稿可以改名后另存为新方案，原快照不会被隐式改变。
- 未保存修改提示：加载方案后编辑雨量、雨型、空间分区、气候分区或方案名称，界面会标记当前草稿已变化，明确区分“覆盖原方案”和“另存为新快照”。
- 方案列表审计信息：列表显示时间雨型、空间分区数/均匀模式、证据等级或来源类型及方案 ID；详情和绑定提示保留 `source_reference`、`evidence_class`、事件起止时间和重构说明。
- CSV 导入：接受 `elapsed_minutes` 或 ISO-8601 `timestamp`，以及二选一的 `depth_mm_per_interval` / `intensity_mm_per_hour`；缺测、重复时间、不规则步长和负值会被拒绝。
- 人工编辑器：5 分钟节点可通过滑杆或数值框编辑，可选择拖动时保持总雨量，并支持均匀初始化、按当前总量归一化、累计量与峰值即时显示；超过 24 小时的高频序列建议改用 CSV。
- 隔离与完整性：HTTP 保存目录按租户和用户隔离；同一方案 ID 不允许被不同内容静默覆盖，加载时验证持久化 SHA-256。

## 接口

- `GET /api/abu-dhabi/flood/rainfall/profiles`：获取气候分区、雨型模板和已登记 Zone B 方案。
- `POST /api/abu-dhabi/flood/rainfall/profiles/validate`：校验并返回标准化雨型方案。
- `POST /api/abu-dhabi/flood/rainfall/preview`：返回时间序列预览、mm/时段、mm/h 和总量统计。
- `POST /api/abu-dhabi/flood/rainfall/forcing`：输出 SWMM、ANUGA 或商业模型适配器使用的统一强迫交换契约；商业模型仍需供应商适配器转换为其原生工程文件。
- `POST /api/abu-dhabi/flood/rainfall/forcing/package`：下载包含 `manifest.json`、`profile.json`、`rainfall_timeseries.csv`、`spatial_zones.geojson` 和边界声明的标准 ZIP；SWMM 使用 mm/h，ANUGA 使用 m/s，商业模型包保持厂商中立。
- `POST /api/abu-dhabi/flood/rainfall/profiles`：校验并保存方案。
- `PUT /api/abu-dhabi/flood/rainfall/profiles/{profile_id}`：显式覆盖已有方案；可传 `expected_profile_hash_sha256` 做并发保护，冲突返回 409。
- `DELETE /api/abu-dhabi/flood/rainfall/profiles/{profile_id}`：删除当前用户的方案快照；不会删除客户原始雨量数据。
- `GET /api/abu-dhabi/flood/rainfall/profiles/saved`：列出当前用户私有目录中的已保存方案。
- `GET /api/abu-dhabi/flood/rainfall/profiles/{profile_id}`：读取单个标准化方案。
- `GET /api/abu-dhabi/flood/rainfall/profiles/{profile_id}/csv`：下载标准相对时间 CSV。
- `POST /api/abu-dhabi/flood/rainfall/profiles/import`：校验 CSV 导入内容但不自动保存；可传 `text/csv`，或 JSON `{ "csv": "...", "metadata": {} }`。

## 模型映射

### 一维 SWMM

`rainfallProfile` 或 `rainfallSeries` 优先于旧的 `rainfallPattern` 字段；已校验的序列写入 `[TIMESERIES]`。Zone B 旧接口保持兼容。若 SWMM 输入带有 `[POLYGONS]` 子汇水区边界，系统会用子汇水区中心点匹配地图雨量区，自动生成多套 `[RAINGAGES]` / `[TIMESERIES]` 并完成绑定；没有边界时，回执会明确标记未应用，而不会静默使用错误空间雨量。

### 二维 ANUGA

面雨直接驱动已支持将 5 分钟雨量序列传入 `rainfall_rate(x, y, t)`；GeoJSON 分区在进入模型前转换至 EPSG:32640，并按网格三角形中心点应用分区系数，未覆盖区域使用默认系数。运行回执记录空间模式和分区数量。

### 一二维耦合

耦合 SWMM 输入复用同一雨型契约，保证一维输入与二维强迫的时间轴、总量和来源一致。空间分区真正进入耦合结果前，仍需完成 SWMM 子汇水区空间映射和接口交换边界的工程验收。

### Al Bateen 试点入口

Al Bateen 5 m 客户 DTM 高分辨率服务已通过鉴权 API 注册：工作流状态、预计算结果库、新建运行、最新运行、单次运行、地图和时间序列共 7 个入口。该链路使用 10 m / 20 m 本地计算网格，不把全市 250 m GWM 结果插值冒充本地水动力结果；现阶段仍属于未校准诊断资产。

## 运行前硬校验

1. 单位必须明确：输入值为 mm/时间步，模型内部转换为 mm/h。
2. 时间步必须为 5 分钟的整数倍；当前二维直接运行要求 5 分钟步长。
3. 区域 ID 不得重复；多边形必须有效；重叠区域必须提供明确优先级。
4. Zone A 不能选择 Zone B 官方 DDF 重现期；没有权威 Zone A 表时只能使用客户时序。
5. `raster` 空间模式当前拒绝运行，待栅格雨量场、时间坐标和缺测规则接入后再开放。
6. 保存的 CSV 使用 `elapsed_minutes`，不伪造事件开始时间；真正绑定模型运行时才由 `start_time` 生成绝对时间戳。

## 下一步工程准入

1. 获取并登记 Zone A 官方 IDF/DDF 表，记录出处、页码、版本和哈希。
2. 建立子汇水区几何/中心点映射，生成多雨量计 SWMM `[RAINGAGES]` 和子汇水区绑定。
3. 对 ANUGA 分区覆盖率、重叠优先级和总量守恒增加网格级质量门。
4. 加入雷达/QPE/站点 NetCDF、CSV、Excel 导入和时区/垂向基准元数据。
5. 在 Al Bateen 先完成 2024 历史暴雨重构、开源模型验证，再将同一雨型方案接入商业水动力模型。
