# GIS Data Agent / MMFE 人工验证操作说明

日期：2026-06-18

复核状态：已按本文档在本机环境复核到 2026-06-18 10:33 CST。页面路径、账号、MinIO bucket、融合质量 API、MMFE readiness API、真实 Sentinel-2 NDVI/Sedona/Iceberg/MinIO/STAC/COG 链路均已实测。聊天框可作为人工交互补充，但 MMFE 生产就绪判断以结构化诊断命令为准。

## 1. 当前运行状态

核心服务已通过 Docker Compose 启动：

- 应用：`http://localhost:8000`
- PostGIS：`localhost:5433`
- MinIO API：`http://localhost:9000`
- MinIO Console：`http://localhost:9001`
- Redis：`localhost:6379`

默认登录账号：

- 用户名：`admin`
- 密码：`admin123`

MinIO 默认账号：

- 用户名：`minio_admin`
- 密码：`local_dev_minio_secret`

当前应用以本地演示模式运行：

- Agent 模型路由：`gemma4-26b-ollama`
- Ollama 地址：`http://host.docker.internal:11434`
- 本机已检测到 `Gemma4:26b`
- `GOOGLE_CLOUD_PROJECT` 可为空；当前本地 Ollama/Gemma 路由不会要求 Google Cloud 项目号。
- 本地验证不依赖在线 Gemini。

已知非阻塞项：

- `MCP Hub: 0/1 servers connected` 可暂时忽略，不影响 GIS Data Agent 主界面、数据库、MinIO、MMFE 本地验证。
- 外部政务/生产标准源、真实 Iceberg/pgvector 生产集群、PDAL/LAZ 后端不在本次本地人工验证范围内。

## 2. 启动与状态检查

如需复查服务状态：

```bash
cd /Users/zhouning/gisdataagent
docker compose ps
```

预期看到：

- `gisdataagent-app-1`：`healthy`
- `gisdataagent-db-1`：`healthy`
- `gisdataagent-minio-1`：`healthy`
- `gisdataagent-redis-1`：`healthy`

查看应用日志：

```bash
docker compose logs --tail=120 app
```

关键预期日志：

```text
[OK] Database:       Connected
[OK] Cloud Storage:  AWSS3 (gis-agent-uploads)
Your app is available at http://0.0.0.0:8000
```

## 3. 基础 UI 验证

1. 浏览器打开 `http://localhost:8000`。
2. 使用 `admin / admin123` 登录。
3. 确认主工作台加载成功，聊天区、地图/数据面板、右侧功能面板可见。
4. 在右侧数据面板中检查以下入口是否能打开：
   - 语义层
   - 融合质量
   - 运行日志
   - 能力清单

通过标准：

- 页面无白屏。
- 登录后不反复跳回登录页。
- 右侧 Tab 切换不报错。

## 4. MMFE 语义融合成果验证

本地已有 TWM/MMFE 验证包：

```text
data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/
```

重点文件：

- `twm_mmfe_semantic_product.json`
- `twm_mmfe_business_view.csv`
- `twm_mmfe_field_semantics.csv`
- `twm_mmfe_value_domain_audit.csv`
- `twm_mmfe_standard_sources.csv`
- `twm_mmfe_semantic_relations.csv`
- `twm_mmfe_semantic_graph.json`
- `twm_mmfe_semantic_trace_cards.json`
- `twm_mmfe_semantic_vectors.pgvector.json`
- `twm_mmfe_publish_plan.json`
- `twm_mmfe_stac_item.json`
- `okf_bundle/`

### 4.1 页面验证：融合质量

1. 登录后进入右侧「工作台」里的数据面板。
2. 先点「平台运营」分组，再点「融合质量」Tab。
3. 点击「刷新」。
4. 页面顶部应显示「MMFE 语义融合就绪」摘要：
   - `验证就绪 是`
   - `生产就绪 否`
   - 核心面应包含「标准源」「值域审计」「语义图谱」「TWM 状态输入」并显示通过状态。
5. 页面调用的结构化诊断 API 为：

```text
/api/fusion/mmfe/readiness
```

6. 当前构建已验证可直接看到真实记录，列表中应出现 `#4 / zonal_statistics`。
7. 点击该行后，下方详情面板应显示 `质量分数 0.6500`、`quality_report` 和 `explainability` JSON。
8. 这次真实运行生成的产物如下：
   - `data_agent/uploads/anonymous/fused_4aa4df72.geojson`
   - `data_agent/uploads/anonymous/fused_4aa4df72.semantic.json`
   - `data_agent/uploads/anonymous/fusion_quality_heatmap_bdda2263.geojson`
9. 这条记录来自真实 Sentinel-2 NDVI 栅格参与的融合链路；项目面仍是 TWM demo contract fixture，但不是空表、模拟接口或只看静态文档。
10. 自动化复核命令：

```bash
cd /Users/zhouning/gisdataagent
node /Users/zhouning/node_modules/playwright/cli.js test mmfe_fusion_quality.spec.ts --config=tests/e2e/playwright.mmfe.config.ts --project=chromium
```

自动化截图：

```text
tests/e2e/screenshots/mmfe_fusion_quality_e2e.png
```

### 4.2 页面验证：语义层

1. 打开「语义层」Tab。
2. 点击刷新或自动注册入口。
3. 检查已注册表、未注册表、字段语义标注列表是否能加载。
4. 在预览输入框中输入：

```text
查询建设项目与永久基本农田冲突的图斑
```

通过标准：

- 请求能返回结构化语义解析结果，或在当前样例表未注册时给出明确空结果/提示。
- 页面不出现 500/白屏。

### 4.3 结构化验证：MMFE/TWM 语义融合生产就绪

生产就绪判断不要只依赖聊天框自由回答。请优先运行结构化诊断：

```bash
cd /Users/zhouning/gisdataagent
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python -m pytest data_agent/test_fusion_semantic_product_diagnostics.py -q
```

通过标准：

- 测试通过。
- 诊断状态为 `validation_ready_with_production_gaps`。
- `standard_source_registry`、`value_domain_audit`、`semantic_graph`、`semantic_trace_cards`、`twm_state_input`、`semantic_relations`、`hard_constraints`、`multi_objective_interface` 均为 `pass`。
- `production_authority` 和 `production_metadata_contract` 为 `warn`，原因是当前 TWM 验证包仍包含 synthetic/not-for-production 数据，不能直接用于生产自然资源治理决策。

也可以在聊天框输入以下内容做人工交互补充：

```text
请检查当前 TWM MMFE 语义融合产品的生产就绪情况，并说明标准源、值域审计、语义图谱和 TWM 状态输入是否齐全。
```

聊天框通过标准只作为人工参考：不再出现 `GOOGLE_CLOUD_PROJECT not found`；回答应能提到上述核心面和生产限制。若聊天回答不完整，以结构化诊断为准。

## 5. MinIO / Lakehouse 验证

浏览器打开：

```text
http://localhost:9001
```

登录：

```text
minio_admin / local_dev_minio_secret
```

检查 bucket：

- `gis-agent-uploads`
- `gis-agent-lakehouse`

通过标准：

- 两个 bucket 存在。
- 能进入 bucket 浏览对象。

命令行复核：

```bash
docker run --rm --network gisdataagent_agent-net --entrypoint sh \
  -e MINIO_ROOT_USER=minio_admin \
  -e MINIO_ROOT_PASSWORD=local_dev_minio_secret \
  minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -c 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc ls local'
```

预期包含：

```text
gis-agent-lakehouse/
gis-agent-uploads/
```

## 6. 可选命令行验证

在宿主机执行：

```bash
cd /Users/zhouning/gisdataagent
curl -I http://localhost:8000
```

预期：

```text
HTTP/1.1 200 OK
```

确认默认账号：

```bash
docker exec gisdataagent-db-1 psql -U postgres -d gis_agent \
  -c "SELECT username, role, auth_provider FROM agent_app_users;"
```

预期包含：

```text
admin | admin | password
```

## 7. 真实数据端到端验证

完整真实数据链路使用本地 TWM demo 项目面和真实 Sentinel-2 L2A NDVI GeoTIFF：

- 矢量输入：`data_agent/test_data/twm_bishan_demo/synthetic_projects.geojson`
- 栅格输入：`data_agent/test_data/twm_bishan_demo/real_imagery/sentinel2_l2a_ndvi.tif`
- 输出：`s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/spark_smoke/`

运行完整 Spark/Sedona/Iceberg/MinIO/STAC smoke：

```bash
cd /Users/zhouning/gisdataagent
bash scripts/smoke_mmfe_baked_spark_runtime.sh
```

通过标准：

- 命令最后输出 `[mmfe-baked-runtime] ok`。
- Spark-MinIO business summary 读写通过。
- Iceberg 表 `mmfe.gis_fusion.semantic_products_smoke` 写入并读回 1 行。
- Sedona 项目-永久基本农田空间叠加输出 39 条关系。
- 真实 Sentinel-2 NDVI GeoTIFF 可读，SRID 为 EPSG:32648。
- NDVI zonal stats 输出 60 条项目关系，其中 20 条为 observed。
- 项目级 NDVI clipped GeoTIFF 输出 3 个，并可读回统计。
- STAC 注册输出 3 个 `mmfe-derived-raster-assets` item。

运行语义产品物化与 STAC 发布：

```bash
cd /Users/zhouning/gisdataagent
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/smoke_mmfe_minio_materialize.py \
  --endpoint-url http://localhost:9000 --include-geoparquet

PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/smoke_mmfe_minio_stac_python.py \
  --endpoint-url http://localhost:9000 \
  --expect-product-id sfp-twm-dc2a707aabda0c01
```

通过标准：

- materialize 输出 `status=ok`，上传 manifest、business view 和 GeoParquet 三个对象。
- STAC Python 发布输出 `status=ok`，读回 item id 为 `sfp-twm-dc2a707aabda0c01`。

可选：把 Sedona 生成的 NDVI clip GeoTIFF 转为 COG 并发布静态 STAC catalog：

```bash
cd /Users/zhouning/gisdataagent
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/smoke_mmfe_rasterio_cog_materialize.py --max-assets 3
```

通过标准：

- 输出 `status=ok`。
- `cog_count=3`、`materialized_count=3`、`stac_published_count=3`。
- 读回 STAC catalog id 为 `mmfe-local-static-stac`。

## 8. 停止与重启

停止核心服务：

```bash
cd /Users/zhouning/gisdataagent
docker compose stop app db redis minio
```

重新启动核心服务：

```bash
cd /Users/zhouning/gisdataagent
docker compose up -d db minio minio-bucket-init redis app
```

如果修改了 `docker-entrypoint.sh` 或依赖镜像内容：

```bash
docker compose up -d --build app
```
