# 地理编码 API 参考

## 高德地理编码 API

### 地理编码（地址 → 坐标）
- 接口: `https://restapi.amap.com/v3/geocode/geo`
- 参数: `address`(必填), `city`(可选), `key`(必填)
- 返回: `location`(经纬度), `formatted_address`, `level`(精度级别)

### 逆地理编码（坐标 → 地址）
- 接口: `https://restapi.amap.com/v3/geocode/regeo`
- 参数: `location`(经纬度,必填), `radius`(搜索半径m), `extensions`(base/all)
- 返回: `formatted_address`, `addressComponent`(省/市/区/街道/门牌号)

### 批量地理编码
- 最大批量: 10 个地址/次
- 接口: `https://restapi.amap.com/v3/geocode/geo?batch=true`
- 参数: `address` 多个地址用 `|` 分隔

### 精度级别 (level)
| 级别 | 含义 |
|------|------|
| 国家/省/市/区 | 行政区划级别匹配 |
| 兴趣点 | POI 级别匹配 |
| 门牌号 | 精确门址匹配 |
| 道路 | 道路级别匹配 |

## 天地图地理编码 API

### 地理编码
- 接口: `https://api.tianditu.gov.cn/geocoder`
- 参数: `ds={"keyWord":"地址"}`, `tk`(密钥)
- 返回: `location.lon`, `location.lat`

### 逆地理编码
- 接口: `https://api.tianditu.gov.cn/geocoder`
- 参数: `postStr={"lon":116.4,"lat":39.9,"ver":1}`, `type=geocode`, `tk`
- 返回: `formatted_address`, `addressComponent`

## 注意事项
- 高德坐标系: GCJ-02（火星坐标系），与 WGS-84 有偏移
- 天地图坐标系: CGCS2000（与 WGS-84 差异可忽略）
- 批量编码建议控制 QPS（高德免费 100次/日/key）
