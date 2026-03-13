---
name: knowledge-retrieval
description: "知识库检索与管理技能。支持创建私有知识库、上传文档（文本/PDF/Word）、语义搜索，实现基于私有知识的RAG增强问答。"
metadata:
  domain: general
  version: "1.0"
  intent_triggers: "知识库 knowledge RAG 文档检索 私有知识 retrieval 查询知识 知识管理 上传文档"
---

# 知识库检索与管理技能

## 概述

本技能用于管理和检索用户私有知识库。用户可上传领域文档（城市规划规范、土地利用标准、技术规范等），系统自动分段并生成语义向量索引。分析时可通过语义搜索检索相关知识，增强回答的准确性和专业性。

## 支持的文档类型
- 纯文本 (.txt)
- Markdown (.md)
- PDF (.pdf) — 自动提取文本（最多50页）
- Word (.docx) — 自动提取段落文本

## 标准工作流程

### 1. 创建知识库
使用 `create_knowledge_base` 创建命名知识库：
- 按主题组织（如"城市规划规范"、"环保标准"、"项目文档"）
- 可设置是否共享给团队

### 2. 添加文档
使用 `add_document_to_kb` 上传文档：
- 系统自动按段落分块（约500字符/块，50字符重叠）
- 使用 Gemini text-embedding-004 生成向量索引
- 嵌入失败时仍保存文本，后续可重新索引

### 3. 语义搜索
使用 `search_knowledge_base` 进行语义检索：
- 基于余弦相似度排序
- 支持指定知识库或跨库搜索
- 返回最相关的 top_k 个文档片段

### 4. 获取上下文
使用 `get_kb_context` 获取格式化的检索结果：
- 直接可用于增强 LLM 回答
- 包含相关度评分和来源信息

## 使用场景
- 用户上传项目相关的规划文件、标准文档、技术规范
- 分析时自动检索相关知识提供参考依据
- 基于私有文档回答领域专业问题
- 团队共享知识库协作

## 可用工具
- `create_knowledge_base`: 创建知识库
- `add_document_to_kb`: 上传文档到知识库（自动分段+向量化）
- `search_knowledge_base`: 语义搜索知识库
- `get_kb_context`: 获取格式化的检索上下文
- `list_knowledge_bases`: 列出用户可访问的知识库
- `delete_knowledge_base`: 删除知识库及所有文档

## 注意事项
- 每用户最多创建 20 个知识库
- 每个知识库最多 100 篇文档
- 单文档最大 5MB 文本
- PDF 最多提取 50 页
- 向量索引依赖 Gemini API，离线时仅支持文本存储
