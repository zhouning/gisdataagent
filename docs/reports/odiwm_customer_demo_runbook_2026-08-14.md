# 本体驱动的灌区条件推演运行手册

**适用场景**：2026-08-14 客户交流

**系统定位**：当前版本使用合成灌区数据，提供“本体语义网络 + 后端权威的确定性守恒情景推演 + Proposal 人工审查”的可审计闭环。它已经接入正式 Chainlit、JWT、PostgreSQL、租户隔离和审批 authority，但不代表真实灌区的校准模型、调度系统或设备控制系统。

## 现场前置检查

1. 登录 GIS 数据平台，在“分析与模型 → 世界模型”中选择“灌区世界模型”。
2. 确认顶部状态条同时显示“后端服务运行”“合成灌区数据”和“不连接生产控制”。
3. 默认参数应为：上游供水下降 20%，西支渠时段后移 6 小时，当前查看 Candidate B。
4. 账号必须有 tenant 绑定；执行人工审查的账号还必须登记在 `gda_control.approval_principal` 且处于可用、可审批状态。

## 正式应用启动

本地客户交流使用正式 Chainlit 应用，不启动独立 Starlette 或 Vite 演示服务。应用用户连接 PostgreSQL，migration authority 使用管理员连接应用迁移：

```bash
cd /Users/zhouning/gisdataagent
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5433
export POSTGRES_DATABASE=gis_agent
export POSTGRES_USER=agent_user
export POSTGRES_PASSWORD=change_me_strong_password
export CHAINLIT_AUTH_SECRET='<至少 32 字符的部署密钥>'
uv run python -m data_agent.migration_runner status
uv run chainlit run data_agent/app.py --headless --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000/`，完成正式登录后，从平台导航进入“灌区世界模型”。若 migration 状态不是 `in_sync`，先由部署人员按仓库规定运行 migration authority；应用不会在启动时偷偷修改 schema。应用重启后，运行、Proposal 审核状态和审计事件应从 PostgreSQL 恢复。

## 五分钟演示脚本

### 1. 先讲问题（约 30 秒）

> “我们先不把它描述成完整灌区世界模型，而是看一个可审计的窄闭环：如果未来 24 小时上游可供水量下降 20%，在一个小型合成网络中，哪些田块会产生供水缺口，候选配水方案是否改善结果。”

强调：当前输入是情景参数，不是实测预报；水库、渠段、闸门、分水口和田块均为合成对象。

### 2. 展示语义网络（约 1 分钟）

依次点击 `R1`、`C1`、`C3`、`D2` 和 `F4`。在右侧切换 `Object`、`Link`、`State`、`Constraint` 标签。

建议说明：

- `Object` 显示稳定 ID、类型和业务角色；
- `Link` 显示上游、下游和供应关系；
- `State` 显示当前冻结的流量、配水比例和时延假设；
- `Constraint` 显示容量上限、守恒残差，以及超容量时“阻断并复核”的处理方式。

### 3. 比较三个方案（约 1 分钟）

点击“运行推演”，前端通过 API 提交参数，后端创建一个新的版本化运行，再查看 `Baseline`、`Candidate A`、`Candidate B` 对比表。

- `Baseline`：保持 55% / 45% 原配水比例，不调整西支渠时段；
- `Candidate A`：仅将西支渠供水时段后移；
- `Candidate B`：同时调整时段和东、西支渠配水比例。

关注指标：到田水量、供水缺口、尾端最低保障、公平 CV、容量违规和水量账残差。说明“残差为 0”只表示当前合成账本在这组显式假设下闭合。

### 4. 做一个可见的反事实变化（约 1 分钟）

将上游供水下降改为 30%，先观察黄色提示“参数已改变，结果区等待重新运行”，然后点击“运行推演”。再把西支渠时段后移改为 10 小时并重复运行。

说明：参数改变后必须显式运行，避免把未确认的编辑值误认为已产生的结果。

### 5. 收束到 Proposal 和边界（约 1 分钟）

回到 Candidate B，展示 Proposal 的三步动作和“待人工审查”状态。填写审核意见后点击“通过审查（不执行）”或“退回修改”，明确说：

- Proposal 是候选动作序列，不是自动执行命令；
- 当前系统不调用闸门、泵站或生产 API；
- 审核请求由后端状态机处理，审核人、时间、意见和结果写入运行审计；已经审核的 Proposal 不能原地改审，需重新运行产生新版本；
- 运行结果写入 `gda_control.irrigation_world_model_run`，审批使用现有 `ApprovalCase`，管线事件写入 append-only 审计表；
- 当前没有训练 JEPA，也没有把美国水库原始数据直接用于客户展示；
- 下一步需要真实灌区对象、拓扑、量测、调度规则和独立验证窗口，才能进入模型校准和离线回放。

## 客户追问的建议回答

**问：这是不是已经实现了 JEPA？**

答：不是。当前系统复用了对象—关系—状态的语义组织方式和确定性守恒推演。JEPA 或其他学习型潜在状态模型属于后续可验证的加速支线，必须先有足够时空观测、独立验证窗口和对照实验。

**问：结果能否直接指导真实灌溉？**

答：不能。现在只支持模型条件下的方案比较。真实应用要先完成本体映射、参数校准、数据质量门禁、安全约束和人工复核，首期也不建议接入自动控制。

**问：为什么不用 MCTS 找全局最优？**

答：当前问题更适合先用守恒约束下的规则、MPC 或 MILP 做可解释基线。MCTS 是否有增量，应在离线基准上比较后再决定，不预设算法胜者。

**问：美国水库数据能否作为灌区证明？**

答：不能。它只能作为跨域研究和方法对照证据，不能替代中国灌区数据，也不应直接当作客户现场的原始数据展示。

## 保底材料

- 客户交流 Word：[odiwm_client_exchange_2026-08-14.docx](./odiwm_client_exchange_2026-08-14.docx)
- 客户交流 PPT：[odiwm_client_exchange_2026-08-14.pptx](./odiwm_client_exchange_2026-08-14.pptx)
- 技术论证底稿：[odiwm_customer_exchange_2026-08-14.docx](./odiwm_customer_exchange_2026-08-14.docx)
- 设计方案：[ontology_driven_irrigation_world_model_design_2026-08-14.md](../designs/ontology_driven_irrigation_world_model_design_2026-08-14.md)
- 需求评估：[odiwm_requirement_assessment_2026-08-14.md](./odiwm_requirement_assessment_2026-08-14.md)
