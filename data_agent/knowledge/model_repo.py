"""
知识管理层 — 数据模型库

对接 EA 在线仓库，解析 EA Native XMI 格式的数据模型。
输出结构化的：业务域 → 实体对象 → 字段定义 + 关系。

Phase 1: 解析 02统一调查监测.xml（三调场景）
Phase 2: 支持全量 10 个业务域
"""

from __future__ import annotations

# TODO Phase 1: 实现 EA XMI 解析器
# 输入: 自然资源全域数据模型/02统一调查监测.xml
# 输出: JSON 结构 — 实体列表 + 字段定义 + 关系
