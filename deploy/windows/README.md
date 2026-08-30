# Windows 内置 GIS 运行时

GIS Data Agent 的离线接入不依赖 ArcPy、ArcGIS Pro、ArcPy MCP、容器或联网安装。发布包必须把 `pyogrio`、`geopandas`、`rasterio`、`shapely`、`pyarrow`、`pyproj` 以及对应的 Windows native DLL 一起放入离线 wheelhouse，并在内网主机上执行：

```powershell
python -m pip install --no-index --find-links D:\GDA_WHEELHOUSE -r requirements-gis-runtime.txt
python scripts\preflight_windows_ingest.py --mode production --create-directories
```

`pyogrio` wheel 自带 GDAL 的 OpenFileGDB 驱动，负责 FileGDB/SHP 读取；`geopandas + pyarrow` 负责 GeoParquet/GPKG 写入；`rasterio` 负责 GeoTIFF/COG。外部 `ogr2ogr`、`ogrinfo`、`gdal_translate` 只作为可选增强，不应写入生产前置条件。

这不是只读预览适配器。GIS Data Agent 的默认工具路径使用同一套 Python GIS 运行时完成投影、缓冲、裁剪、叠加/差异、空间连接、分区统计、栅格转矢量、坡度/坡向派生、几何有效性检查和标准化物化；Paper9 Tool 1/4 也通过该运行时读取 FileGDB、DEM 并写出结果。ArcPy 工具仍可作为有 ArcGIS 授权时的兼容增强，但不会被现场流程自动选择。

`requirements-gis-runtime.txt` 是内置 GIS 适配器的最低补充清单；完整 GIS Data Agent 发布包仍需按项目 `requirements.txt` 安装应用、API、日志和 Paper9 依赖。所有 wheel、GDAL/PROJ native DLL 和数据目录必须在联网环境打包后，以 U 盘或受控介质转入隔离网，现场安装命令使用 `--no-index`。

版本必须与项目发布清单和 Python 小版本一致，不能在现场临时联网升级。预检必须实际报告 `filegdb_reader=true`、`vector_writer=true` 和 `raster_cog_writer=true` 后才允许启动 worker。
