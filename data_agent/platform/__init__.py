"""
GIS Data Agent — 底座调用层 (Platform Layer)

封装时空数据治理平台的 REST API 为 GIS Data Agent 可调用的接口。
不修改底座内部逻辑，仅做 API 封装和适配。

模块：
- datasource_api: 数据源管理 API 封装
- metadata_api: 元数据读取 API 封装
- governance_api: 质检/治理执行 API 封装
- asset_api: 数据资产/数据服务 API 封装
"""
