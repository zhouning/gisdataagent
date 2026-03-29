#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fill design document - Part 1: Overview and Architecture sections
"""
import sys
import os

# Add docx-official skill to path
skill_root = r"C:\Users\zn198\.claude\skills\docx-official"
sys.path.insert(0, skill_root)

from scripts.document import Document

def fill_overview_section(doc):
    """Fill the 概述 (Overview) section"""
    # Find the overview heading
    overview_heading = doc["word/document.xml"].get_node(tag="w:p", contains="概述")

    # The next paragraph after heading should be the existing description
    # We'll insert additional content after it

    overview_content = """
本产品基于Google Agent Developer Kit (ADK) v1.27构建，是一个企业级地理信息智能分析平台。系统采用LLM驱动的语义路由架构，通过意图分类将用户请求分发至三条专业化处理管线：数据治理管线、土地利用优化管线（基于深度强化学习）和通用空间智能管线。

核心技术特性：
• 多模态数据融合：支持矢量、栅格、表格、点云等10种数据源类型
• 智能语义层：三层元数据架构（YAML目录+数据库注册表+自定义域）
• 用户自服务扩展：自定义Skills、User Tools、多Agent工作流编排
• 测绘质检智能体：GB/T 24356标准合规，30类缺陷分类，SLA工作流
• 企业级可观测性：Prometheus指标、结构化日志、分布式追踪
• 多租户隔离：基于ContextVar的用户沙箱、RBAC权限控制、RLS数据隔离

系统版本：v15.8
代码规模：96个测试文件，2680+测试用例，202个REST API端点，48个数据库表
技术栈：Python 3.13 + React 18 + PostgreSQL 16 + PostGIS 3.4
"""

    # Insert after the existing paragraph
    existing_para = doc["word/document.xml"].get_node(tag="w:p", contains="本文档主要用于描述")
    doc["word/document.xml"].insert_after(existing_para,
        f'<w:p><w:r><w:t>{overview_content}</w:t></w:r></w:p>')

    print("✓ Overview section filled")

def fill_component_architecture(doc):
    """Fill 总体组件/服务架构 section"""
    heading = doc["word/document.xml"].get_node(tag="w:p", contains="总体组件/服务架构")

    content = """
系统采用分层微服务架构，包含以下核心组件：

【接入层】
• Chainlit UI Server (端口8000)：提供Web界面和WebSocket连接
• REST API Gateway (202个端点)：统一API入口，JWT认证
• OAuth2 Provider：支持Google/GitHub第三方登录

【应用层】
• Intent Router：基于Gemini 2.0 Flash的语义意图分类器
• Pipeline Orchestrator：三条专业管线的调度引擎
  - Optimization Pipeline (优化管线)：ParallelAgent → Processing → AnalysisQualityLoop → Viz → Summary
  - Governance Pipeline (治理管线)：Exploration → Processing → ReportLoop
  - General Pipeline (通用管线)：Processing → Viz → SummaryLoop
• Dynamic Planner Agent：跨管线任务编排（可选启用）
• Custom Skills Engine：用户自定义Agent实例化引擎
• Workflow Engine：DAG工作流执行器，支持Cron调度和Webhook

【工具层】
• 36个Toolset模块：涵盖空间处理、分析、可视化、治理、融合等
• MCP Hub：Model Context Protocol集成中心，支持stdio/SSE/HTTP三种传输协议
• User Tools Engine：用户自定义工具执行引擎（http_call/sql_query/file_transform/chain）

【数据层】
• PostgreSQL 16 + PostGIS 3.4：主数据库（48张表）
• Redis (可选)：实时流数据缓存
• 对象存储适配器：支持Huawei OBS/AWS S3/GCS
• Data Lake Catalog：统一数据资产目录，四层元数据架构

【AI服务层】
• Model Gateway：任务感知的模型路由（Gemini 2.0/2.5 Flash/Pro）
• Context Manager：可插拔上下文提供器，Token预算管理
• Prompt Registry：版本化提示词管理，环境隔离（dev/prod）
• Evaluation Framework：场景化评估框架，自定义指标

【子系统层】（测绘质检专用）
• CV Detection Service (端口8010)：基于YOLO的视觉检测
• CAD Parser Service (端口8011)：CAD/3D文件解析
• Reference Data Service (端口8012)：参考数据服务
• Tool MCP Servers：ArcGIS Pro/QGIS/Blender工具桥接

【监控层】
• Prometheus Exporter：25+指标（LLM/Tool/Pipeline/Cache/CB/HTTP）
• Structured Logger：JSON格式日志，trace_id关联
• Alert Engine：阈值告警，Webhook/WebSocket推送
• Health Check：/health, /ready, /metrics端点
"""

    doc["word/document.xml"].insert_after(heading,
        f'<w:p><w:r><w:t>{content}</w:t></w:r></w:p>')

    print("✓ Component architecture filled")

def fill_data_architecture(doc):
    """Fill 总体数据架构 section"""
    heading = doc["word/document.xml"].get_node(tag="w:p", contains="总体数据架构")

    content = """
数据架构采用"湖仓一体"设计，支持结构化、半结构化和非结构化数据的统一管理。

【数据分层】
1. 原始数据层 (Raw Layer)
   • 用户上传文件：uploads/{user_id}/ 沙箱隔离
   • 支持格式：Shapefile, GeoJSON, GPKG, KML, CSV, Excel, TIFF, PDF, DOCX
   • 自动格式检测和坐标系识别

2. 数据湖层 (Data Lake)
   • agent_data_assets表：统一资产目录
   • 四层元数据：Technical/Business/Operational/Lineage
   • 版本管理：agent_asset_versions表，快照存储
   • 血缘追踪：上下游依赖关系图

3. 语义层 (Semantic Layer)
   • 三级架构：
     - YAML静态目录 (semantic_catalog.yaml)：领域定义、列域、区域分组
     - 数据库注册表 (agent_semantic_registry)：表/列级语义标注
     - 自定义域 (agent_semantic_domains)：用户定义层次结构
   • 5分钟TTL缓存，写入时失效

4. 应用层 (Application Layer)
   • PostGIS空间数据库：GEOMETRY(Point/Polygon, 4326)
   • 时序数据：stream_locations表（TimescaleDB-ready）
   • 向量索引：pgvector ivfflat，64维L2归一化嵌入
   • 知识图谱：agent_kb_entities + agent_kb_relations

【数据流转】
用户上传 → 格式转换 → 数据剖析 → 语义标注 → 入湖登记 → 管线处理 → 结果输出 → 版本归档

【数据治理】
• 数据分类分级：敏感度标签（public/internal/confidential/restricted）
• 数据脱敏：字段级脱敏规则（agent_data_masking_rules）
• 访问控制：RLS策略 + 审批流程（agent_data_requests）
• 质量监控：agent_quality_trends表，6维度评分（完整性/准确性/一致性/时效性/唯一性/有效性）

【数据安全】
• 行级安全 (RLS)：25+张表启用，基于app.current_user上下文变量
• 列级加密：敏感字段加密存储（预留）
• 审计日志：agent_audit_log表，90天保留期
• 备份策略：PostgreSQL PITR + 对象存储快照
"""

    doc["word/document.xml"].insert_after(heading,
        f'<w:p><w:r><w:t>{content}</w:t></w:r></w:p>')

    print("✓ Data architecture filled")

def main():
    print("Starting Part 1: Overview and Architecture sections...")

    doc = Document('unpacked_design_doc', author="Claude", track_revisions=False)

    fill_overview_section(doc)
    fill_component_architecture(doc)
    fill_data_architecture(doc)

    doc.save()
    print("\n✓ Part 1 completed successfully")

if __name__ == "__main__":
    main()
