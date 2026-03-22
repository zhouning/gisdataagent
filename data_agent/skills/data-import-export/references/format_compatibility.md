# 空间数据格式兼容性矩阵

## 支持的输入格式

| 格式 | 扩展名 | 矢量/栅格 | 多图层 | 备注 |
|------|--------|----------|--------|------|
| Shapefile | .shp (+.dbf/.shx/.prj) | 矢量 | 否 | 需全部 4 个关联文件 |
| GeoJSON | .geojson/.json | 矢量 | 否 | UTF-8 编码 |
| GeoPackage | .gpkg | 矢量+栅格 | 是 | 推荐的现代格式 |
| File Geodatabase | .gdb (目录) | 矢量 | 是 | Esri 格式，需 OpenFileGDB 驱动 |
| KML | .kml | 矢量 | 否 | Google Earth 格式 |
| KMZ | .kmz | 矢量 | 否 | 压缩的 KML |
| CSV | .csv | 表格 | 否 | 需含坐标列 (lon/lat) |
| Excel | .xlsx/.xls | 表格 | 否 | 需含坐标列 |
| GeoTIFF | .tif/.tiff | 栅格 | 否 | 遥感影像/DEM |

## 编码兼容性

| 编码 | 支持度 | 建议 |
|------|--------|------|
| UTF-8 | 完全支持 | 推荐 |
| GBK/GB2312 | 需手动指定 | Shapefile 中文常用 |
| ISO-8859-1 | 支持 | 西文默认 |

### Shapefile 中文编码
Shapefile 使用 .cpg 文件声明编码。若缺失 .cpg，默认 ISO-8859-1 会导致中文乱码。
解决方法: 创建 .cpg 文件，内容为 `UTF-8` 或 `GBK`。

## CRS 兼容性

| CRS | EPSG | 用途 |
|-----|------|------|
| WGS 84 | 4326 | GPS/国际通用地理坐标 |
| CGCS2000 | 4490 | 中国国家大地坐标系（地理） |
| CGCS2000 / 3° Zone | 4526-4554 | 投影坐标（按经度分带） |
| WGS 84 / UTM | 326xx | 国际通用投影坐标 |
| 西安 80 | 4610 | 旧中国坐标系（逐步淘汰） |

### 注意事项
- 面积/距离计算必须在投影坐标系下进行
- CGCS2000 和 WGS 84 在实际精度要求下可视为等价
- Shapefile 的 .prj 文件声明 CRS，缺失时需手动设定

## ZIP 自动解压

上传 ZIP 文件时自动解压，识别内含的:
- .shp + 关联文件 → Shapefile
- .kml → KML
- .geojson → GeoJSON
- .gpkg → GeoPackage
