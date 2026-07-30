# Gemma 4 决赛资料入口

更新时间：2026-07-30

本目录是 5 分钟路演、3 分钟 Q&A、现场 Demo 和技术审查的单一入口。所有结论按证据类型分层，避免把模型编排评测、算法运行和历史内网记录混成同一种证明。

## 决赛交付

- [可编辑 PPTX](GIS_Data_Agent_Gemma4_Finals_CN.pptx)：6 页主路演 + 5 页 Q&A 附录，已绑定 406 对置换证据。
- [离线 PDF](GIS_Data_Agent_Gemma4_Finals_CN.pdf)：与 PPTX 同次构建，用于断网备份和设备兼容检查。
- 主路演逐字稿目标 `4:40`，预留 `20` 秒；最终文件哈希见 [release_manifest.sha256](release_manifest.sha256)。

## 当前结论

> 2026-07-30 最新真实验收已将县域耕地规划锁定结果更新为 406 对置换；PPTX/PDF 已按同一
> 证据快照重建。录制前仍需按 [verified_demo_script.md](verified_demo_script.md) 完成人工 UI 复核。

GIS Data Agent 的决赛主线已经从固定工作流升级为受控自主 Agent，并明确走向 `LLM + GWM`：

```text
版本与资源预检
-> 检索已验证经验
-> Gemma 4 选择县域规划工具
-> 硬约束审计
-> 通过则写入已验证经验库
-> 失败则最多重规划一次
-> 再失败则停止并转人工
```

当前工程证据：

- Gemma 4 + Google ADK 三类分支各运行 10 次，30/30 通过行为契约。
- 县域耕地空间优化引擎 `0.3.3 / 2.2.3` 已完成真实 MPC 规划；六次函数调用闭环、硬约束校验和同指标空间成果均通过验收。
- 决赛主机预检全部通过：版本、Bishan prepared、3 个 ONNX 成员和 `Gemma4:26b` 标签均就绪。
- 确定性行为契约覆盖首次成功、一次恢复、二次失败转人工、版本阻断和禁止未审计写入。
- 最终镜像运行时回归 `236 passed`，宿主交付契约 `6 passed`，另有接口兼容测试 `52 passed`；Ruff、Python 编译、前端生产构建和 Compose 配置解析通过。
- app、PostGIS 和 Redis 当前均为 `healthy`；前端大包与依赖弃用警告已记录，不能表述为零警告运行。
- 当前县域耕地空间优化引擎是领域化 GWM 原型：状态转移模型集成是动力学内核雏形，MPC 是规划器，硬约束校验负责结果验收；不表述为完整通用 GWM。
- 县域规划可导出约 5 页 A4 图文 PDF，包含指标看板、真实变化地图、六步调用轨迹、逐函数用时和审计表。

## 文档索引

| 文档 | 用途 |
|---|---|
| [scoring_evidence_matrix.md](scoring_evidence_matrix.md) | 按 30/25/20/15/10 权重核对证据、缺口和路演位置 |
| [technical_report.md](technical_report.md) | 决赛技术报告短版，用于快速通读 |
| [GIS_Data_Agent_Gemma4_Finals_Technical_Handbook_CN.md](GIS_Data_Agent_Gemma4_Finals_Technical_Handbook_CN.md) | 深度技术答辩手册源文档，含 9 张正式技术图、关键实现、代码索引和 20 个追问口径 |
| [GIS_Data_Agent_Gemma4_Finals_Technical_Handbook_CN.docx](GIS_Data_Agent_Gemma4_Finals_Technical_Handbook_CN.docx) | 可编辑 Word 版，含二级可点击目录，并保留导航窗格章节树 |
| [GIS_Data_Agent_Gemma4_Finals_Technical_Handbook_CN.pdf](GIS_Data_Agent_Gemma4_Finals_Technical_Handbook_CN.pdf) | 离线 PDF 版，适合比赛设备快速查阅 |
| [assets/diagrams](assets/diagrams) | 技术图的 SVG 可编辑源文件与约 3200 像素宽 PNG 发布文件 |
| [evidence/world_model_bishan_20260730_155442](evidence/world_model_bishan_20260730_155442) | 406 对置换锁定快照：原始汇总、硬约束审核和变化图斑；明确标注为旧三位测试编码 |
| [claim_register.md](claim_register.md) | 哪些话能说、哪些必须限定、哪些不能说 |
| [deployment.md](deployment.md) | 决赛环境部署、预检和验证 |
| [quality_gate_report.md](quality_gate_report.md) | 决赛质量检查报告：精确测试集合、构建结果、运行状态与已知警告 |
| [demo_runbook.md](demo_runbook.md) | 5 分钟现场流程、视频备份和故障预案 |
| [verified_demo_script.md](verified_demo_script.md) | 2026-07-30 真实数据验收后的唯一最新版操作、录屏与逐字口播 |
| [pitch_script.md](pitch_script.md) | 4 分 40 秒逐页逐字口播与强制切屏时间 |
| [video_script.md](video_script.md) | 主备视频、异常恢复和版本阻断的镜头级脚本 |
| [rehearsal_log.md](rehearsal_log.md) | 三轮彩排、投影可读性和五秒故障切换验收 |
| [release_manifest.sha256](release_manifest.sha256) | 冻结决赛交付文件的 SHA-256 完整性清单 |
| [qa.md](qa.md) | 3 分钟 Q&A 短答案；附录 A1–A5 直接对应五个高概率问题 |

## 证据分层

| 层级 | 内容 | 可证明 | 不可证明 |
|---|---|---|---|
| A | 真实 Gemma 4 26B + ADK 重复运行，规划工具为确定性替身 | 工具选择、分支控制、停止与恢复的模型可靠性 | 30 次底层算法计算成功 |
| B | 本机 0.3.3 / 2.2.3 真实 MPC 运行 | 当前代码绑定、GWM 领域原型、实际 MPC、空间产物和硬约束校验 | 完整通用 GWM、v2.2.3 四库全流程重训或部内复测 |
| C | 底层引擎（内部代号 Paper9）交接文档记录的历史内网运行 | 历史版本在目标环境处理真实权威数据的工程可行性 | GIS Data Agent 已在部内生产部署 |
| D | AlphaEarth / OKF | 技术扩展方向和知识治理设计 | 已成为主 Agent 的生产闭环 |

## 当前路演原则

- Gemma 4 是决策与控制面；Google ADK 是 Agent 运行时；PostGIS、GIS 与县域耕地空间优化引擎是确定性行动面。
- 主叙事统一使用“县域耕地空间优化引擎”；`Paper9` 仅作为技术文档中的内部研发代号。
- GWM 关系必须说清：状态转移模型是动力学内核雏形，MPC 使用预测搜索方案，硬约束校验负责结果验收。
- 主 Demo 展示一个成功闭环，异常恢复使用预录视频或已保存轨迹。
- 先讲真实需求与量化证据，再讲技术；Google 技术栈是可信度乘数，不是 Logo 数量。
- AlphaEarth 必须标注 `Tech Preview`；OKF 必须称为知识交换 sidecar。
- 任何自然资源内网表述都必须遵守 [claim_register.md](claim_register.md)。
