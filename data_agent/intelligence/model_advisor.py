"""
智能交互层 — UC-05 推荐数据模型调整方案

输入：数据集元数据 + 通用数据模型（来自 knowledge/model_repo）
输出：模型调整建议清单（新增/修改/删除字段，调整关系）

核心约束：LLM 推理必须引用知识库中的具体规则，不允许无依据发挥。
"""

from __future__ import annotations

# TODO Phase 1: 实现模型推荐逻辑
# Step 1: 读取样例数据元数据（通过 platform/metadata_api）
# Step 2: 用 knowledge/semantic_vocab 做字段语义匹配
# Step 3: 用 knowledge/standard_rules 检查值域合规性
# Step 4: LLM 综合推理（基于结构化分析结果）
# Step 5: 输出调整建议清单
