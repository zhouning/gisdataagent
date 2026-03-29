"""元数据系统集成辅助函数"""
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def register_uploaded_file_metadata(file_path: str) -> Optional[int]:
    """注册上传文件的元数据"""
    try:
        from data_agent.metadata_extractor import MetadataExtractor
        from data_agent.metadata_enricher import MetadataEnricher
        from data_agent.metadata_manager import MetadataManager

        extractor = MetadataExtractor()
        enricher = MetadataEnricher()
        manager = MetadataManager()

        # 提取元数据
        metadata = extractor.extract_from_file(file_path)

        # 增强元数据
        file_name = Path(file_path).name
        metadata = enricher.enrich_geography(metadata)
        metadata = enricher.enrich_domain(metadata, file_name)
        metadata = enricher.enrich_quality(metadata)

        # 注册到数据库
        asset_id = manager.register_asset(
            asset_name=file_name,
            technical=metadata.get("technical", {}),
            business=metadata.get("business", {}),
            operational=metadata.get("operational", {}),
            display_name=file_name
        )

        logger.info(f"Registered metadata for {file_name}, asset_id={asset_id}")
        return asset_id

    except Exception as e:
        logger.warning(f"Failed to register metadata for {file_path}: {e}")
        return None
