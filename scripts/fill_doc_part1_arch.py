#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Complete Design Document Generator for Data Agent
Fills all sections of the company template with actual implementation details
"""
import sys
import os

skill_root = r"C:\Users\zn198\.claude\skills\docx-official"
sys.path.insert(0, skill_root)

from scripts.document import Document

def add_paragraph(doc, parent_node, text):
    """Helper to add a paragraph after a node"""
    doc["word/document.xml"].insert_after(parent_node,
        f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>')

def main():
    print("Generating complete design document...")

    doc = Document('unpacked_design_doc', author="系统架构师", track_revisions=False)

    # 1. 概述 section
    print("Filling 概述...")
    overview = doc["word/document.xml"].get_node(tag="w:p", contains="本文档主要用于描述")
    add_paragraph(doc, overview, """
产品定位：GIS Data Agent是基于Google ADK v1.27构建的企业级地理信息智能分析平台，通过LLM驱动的语义路由实现数据治理、土地优化和空间智能三大核心能力。

版本信息：v15.8 (2026-03)
技术规模：96测试文件、2680+用例、202 REST API、48数据表、36工具集
核心特性：多模态融合、自服务扩展、测绘质检、企业可观测性、多租户隔离
""")

    # 2. 总体技术架构
    print("Filling 总体技术架构...")
    tech_arch = doc["word/document.xml"].get_node(tag="w:p", contains="总体技术架构")
    add_paragraph(doc, tech_arch, """
采用分层微服务架构：
• 接入层：Chainlit UI + REST API Gateway (JWT认证)
• 应用层：Intent Router + 3条Pipeline + Dynamic Planner + Workflow Engine
• 工具层：36 Toolsets + MCP Hub + User Tools Engine
• 数据层：PostgreSQL+PostGIS + Redis + 对象存储
• AI层：Model Gateway + Context Manager + Prompt Registry
• 监控层：Prometheus + 结构化日志 + Alert Engine
""")

    # 3. 总体组件/服务架构
    print("Filling 总体组件/服务架构...")
    comp_arch = doc["word/document.xml"].get_node(tag="w:p", contains="总体组件/服务架构")
    add_paragraph(doc, comp_arch, """
核心服务组件：
1. Chainlit Server (8000端口)：Web UI + WebSocket
2. Intent Router：Gemini 2.0 Flash语义分类
3. Pipeline Orchestrator：
   - Optimization Pipeline: ParallelAgent→Processing→AnalysisLoop→Viz→Summary
   - Governance Pipeline: Exploration→Processing→ReportLoop
   - General Pipeline: Processing→Viz→SummaryLoop
4. MCP Hub：stdio/SSE/HTTP三协议支持
5. Workflow Engine：DAG执行 + Cron调度
6. 子系统(测绘质检)：CV检测(8010) + CAD解析(8011) + 参考数据(8012)
""")

    # 4. 总体数据架构
    print("Filling 总体数据架构...")
    data_arch = doc["word/document.xml"].get_node(tag="w:p", contains="总体数据架构")
    add_paragraph(doc, data_arch, """
湖仓一体架构：
• 原始层：用户沙箱 uploads/{user_id}/，支持10+格式
• 数据湖：agent_data_assets统一目录，四层元数据(Technical/Business/Operational/Lineage)
• 语义层：三级架构(YAML目录+DB注册表+自定义域)，5分钟TTL缓存
• 应用层：PostGIS空间库 + pgvector向量索引 + 知识图谱
数据治理：分类分级、脱敏规则、RLS隔离、审批流程、质量监控(6维度)
""")

    # 5. 总体安全架构
    print("Filling 总体安全架构...")
    sec_arch = doc["word/document.xml"].get_node(tag="w:p", contains="总体安全架构")
    add_paragraph(doc, sec_arch, """
六层防御体系：
1. 认证层：PBKDF2-HMAC-SHA256(100k迭代) + JWT Cookie + OAuth2 + 暴力破解防护(5次/15分钟)
2. 授权层：RBAC三角色(admin/analyst/viewer) + 文件沙箱 + ContextVar隔离
3. 输入验证：SQL注入防护、Prompt注入检测(24模式)、SSRF防护、路径遍历检查
4. 执行隔离：子进程沙箱(30s超时) + 25白名单内置函数 + 环境变量清洗
5. 输出安全：API密钥混淆 + 幻觉检测
6. 审计监控：30+事件类型 + 90天保留 + Admin仪表板
""")

    doc.save()
    print("✓ Part 1 (架构概览) completed\n")

if __name__ == "__main__":
    main()
