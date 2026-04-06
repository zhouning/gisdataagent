"""
GIS Data Agent — 知识管理层 (Knowledge Layer)

存储和检索领域知识，支撑 AI 推理的准确性。
AI 推理必须基于此层的结构化知识，不允许 LLM 无依据"猜"领域知识。

模块：
- semantic_vocab: 语义等价库（GIS 字段语义匹配）
- standard_rules: 标准规则库（数据标准结构化解析）
- model_repo: 数据模型库（EA 仓库对接）
- case_library: 治理案例库（经验沉淀，Phase 2+）
"""
