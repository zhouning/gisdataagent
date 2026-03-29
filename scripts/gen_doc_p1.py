#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Complete Design Document Generator - All Sections"""
import sys
sys.path.insert(0, r"C:\Users\zn198\.claude\skills\docx-official")
from scripts.document import Document

def add_para(doc, after_text, content):
    """Add paragraph after node containing text"""
    node = doc["word/document.xml"].get_node(tag="w:p", contains=after_text)
    doc["word/document.xml"].insert_after(node, f'<w:p><w:r><w:t>{content}</w:t></w:r></w:p>')

doc = Document('unpacked_design_doc', author="架构师", track_revisions=False)

# 1. 概述
add_para(doc, "本文档主要用于描述", """
产品：GIS Data Agent v15.8 - 企业级地理信息智能分析平台
架构：Google ADK v1.27 + LLM语义路由 + 三条专业管线
规模：96测试文件、2680+用例、202 API、48表、36工具集
特性：多模态融合、自服务扩展、测绘质检、可观测性、多租户
""")

# 2. 总体技术架构
add_para(doc, "总体技术架构", """
分层架构：接入层(Chainlit+API) → 应用层(Router+Pipeline+Workflow) → 工具层(36 Toolsets+MCP) → 数据层(PG+PostGIS+Redis) → AI层(Gateway+Context+Prompt) → 监控层(Prometheus+Log+Alert)
""")

# 3. 总体组件/服务架构
add_para(doc, "总体组件/服务架构", """
核心组件：
• Chainlit Server(8000): Web UI + WebSocket
• Intent Router: Gemini 2.0 Flash分类器
• 3条Pipeline: Optimization/Governance/General
• MCP Hub: stdio/SSE/HTTP协议
• Workflow Engine: DAG + Cron
• 子系统: CV(8010) + CAD(8011) + RefData(8012)
""")

# 4. 总体数据架构
add_para(doc, "总体数据架构", """
湖仓一体：原始层(沙箱) → 数据湖(统一目录+四层元数据) → 语义层(三级架构+5分钟缓存) → 应用层(PostGIS+向量+图谱)
治理：分类分级、脱敏、RLS、审批、质量监控(6维)
""")

# 5. 总体安全架构
add_para(doc, "总体安全架构", """
六层防御：认证(PBKDF2+JWT+OAuth2+防暴力) → 授权(RBAC+沙箱+ContextVar) → 输入验证(SQL/Prompt/SSRF/路径) → 执行隔离(沙箱+白名单) → 输出安全(混淆+检测) → 审计(30+事件+90天)
""")

doc.save()
print("✓ Part 1 完成")
