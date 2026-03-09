---
name: collaboration
description: "团队管理、空间记忆、管理员操作与协作技能。支持团队创建、记忆存储检索、审计日志查询和模板管理。"
metadata:
  domain: collaboration
  version: "1.0"
  intent_triggers: "team, share, collaborate, memory"
---

# 协作技能

## 核心能力

1. **团队管理**: `create_team` 创建团队、`invite_member` 邀请成员、`list_teams` 团队列表、`set_member_role` 设置角色、`remove_member` 移除成员
2. **空间记忆**: `save_memory` 保存分析发现/用户偏好、`recall_memories` 检索历史记忆、`list_memories` 列出所有记忆、`delete_memory` 删除记忆
3. **管理员操作**: `usage_summary` 系统使用量统计、`audit_log` 查询审计日志、`list_templates` 列出报告模板
4. **数据资产**: `list_data_assets` 浏览数据目录、`search_data_assets` 搜索资产、`share_asset` 共享资产给团队

## 记忆类型

| 类型 | 用途 | 示例 |
|------|------|------|
| region | 关注区域 | "用户关注斑竹村耕地" |
| viz_preference | 可视化偏好 | "用户偏好热力图" |
| analysis_result | 分析结论 | "FFI=0.45，碎片化中等" |
| custom | 自定义上下文 | "林业规划师视角" |

## 协作工作流

1. 创建团队并邀请成员
2. 使用 `save_memory` 记录关键分析发现
3. 团队成员通过 `recall_memories` 共享分析上下文
4. 使用 `share_asset` 将数据集共享给团队
