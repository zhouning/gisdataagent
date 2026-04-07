# savemyself_connector.py - SaveMyself SaaS数据连接器
"""
Data Agent连接器,用于从SaveMyself SaaS平台获取鼻炎日志数据
位置: D:\adk\data_agent\connectors\savemyself_connector.py
"""

from typing import Dict, Optional
import httpx
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from datetime import date
from .base import BaseConnector


class SaveMyselfConnector(BaseConnector):
    """SaveMyself鼻炎SaaS数据连接器"""

    def __init__(self, config: Dict):
        """
        初始化连接器

        config:
            api_base_url: API基础URL (如 "https://savemyself.example.com")
            api_key: API密钥
            anonymize: 是否匿名化数据 (默认True)
        """
        super().__init__(config)
        self.api_base_url = config["api_base_url"]
        self.api_key = config["api_key"]
        self.anonymize = config.get("anonymize", True)

    async def fetch_data(self, params: Optional[Dict] = None) -> gpd.GeoDataFrame:
        """
        获取鼻炎日志数据

        params:
            user_id: 用户ID (可选,管理员可查询所有用户)
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            min_records: 最小记录数过滤
        """
        params = params or {}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.api_base_url}/api/export/logs",
                params=params,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data:
            raise ValueError("未获取到任何数据")

        # 转换为DataFrame
        df = pd.DataFrame(data)

        # 数据清洗
        df["date"] = pd.to_datetime(df["date"])

        # 位置模糊化 (隐私保护)
        if self.anonymize:
            import numpy as np

            df["latitude"] += np.random.uniform(-0.05, 0.05, len(df))
            df["longitude"] += np.random.uniform(-0.05, 0.05, len(df))

        # 转换为GeoDataFrame
        geometry = [Point(lon, lat) for lon, lat in zip(df["longitude"], df["latitude"])]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

        # 设置时间索引
        gdf = gdf.set_index("date").sort_index()

        return gdf

    async def get_schema(self) -> Dict:
        """获取数据schema"""
        return {
            "name": "savemyself_rhinitis_logs",
            "description": "鼻炎患者日志数据",
            "fields": [
                {"name": "user_id", "type": "integer", "description": "用户ID"},
                {"name": "date", "type": "date", "description": "日期"},
                # 症状
                {"name": "nasal_congestion", "type": "integer", "description": "鼻塞程度(0-10)"},
                {"name": "runny_nose", "type": "integer", "description": "流涕程度(0-10)"},
                {"name": "sneezing", "type": "integer", "description": "打喷嚏频率(0-10)"},
                {"name": "itchiness", "type": "integer", "description": "眼鼻发痒(0-10)"},
                # 环境
                {"name": "temperature", "type": "float", "description": "气温(°C)"},
                {"name": "humidity", "type": "float", "description": "湿度(%)"},
                {"name": "pm25", "type": "float", "description": "PM2.5(μg/m³)"},
                {"name": "pm10", "type": "float", "description": "PM10(μg/m³)"},
                {"name": "no2", "type": "float", "description": "NO₂(μg/m³)"},
                {"name": "o3", "type": "float", "description": "O₃(μg/m³)"},
                {"name": "aqi", "type": "integer", "description": "空气质量指数"},
                # 生活方式
                {"name": "sleep_quality", "type": "integer", "description": "睡眠质量(0-10)"},
                {"name": "stress_level", "type": "integer", "description": "压力水平(0-10)"},
                {"name": "exercise_minutes", "type": "integer", "description": "运动时长(分钟)"},
                # 干预
                {"name": "medications", "type": "text", "description": "用药记录"},
                {"name": "nasal_wash", "type": "boolean", "description": "是否洗鼻"},
                # 空间
                {"name": "latitude", "type": "float", "description": "纬度"},
                {"name": "longitude", "type": "float", "description": "经度"},
                {"name": "geometry", "type": "geometry", "description": "空间位置"},
            ],
        }
