# 5 分钟现场 Demo Runbook

目标：4 分 40 秒完成，预留 20 秒给现场切换或评委打断。操作、数字和逐字口播的唯一最新版见
[verified_demo_script.md](verified_demo_script.md)。

## 1. 六页主线

| 时间 | 页 | 结论 | 屏幕动作 |
|---|---:|---|---|
| 0:00–0:30 | 1 | GIS 问数高频、空间规划高价值，但都要求可执行和可审计 | PPT |
| 0:30–1:05 | 2 | 模型、运行时、确定性行动与治理边界清晰 | PPT |
| 1:05–1:55 | 3 | Gemma 4 26B 由 CQ-125 选出，空间语义被真实执行 | 播放 35 秒锁定视频或实时结果 |
| 1:55–3:25 | 4 | Gemma 4 + ADK 控制 Agent；GWM 领域原型 + MPC 完成空间推演与搜索 | 播放 70 秒加速版真实视频 |
| 3:25–4:20 | 5 | 不是一次 Demo：编排、算法、工程和历史环境证据分层 | PPT 证据表 |
| 4:20–4:40 | 6 | 下一代空间智能体将由 LLM + GWM 共同驱动 | PPT 总结 |

逐字口播见 [pitch_script.md](pitch_script.md)；镜头级录制与字幕验收见 [video_script.md](video_script.md)；三轮实测记录见 [rehearsal_log.md](rehearsal_log.md)。

## 2. 县域耕地空间优化现场提示词

```text
@WorldModelV21 请使用 bishan 数据集运行一次快速县域 MPC 规划，完成硬约束审计，并仅在通过后保存已验证经验。
```

成功时只讲四件事：

1. Gemma 4 选择了 `status -> inspect -> recall -> pipeline -> audit -> commit`。
2. 先完成版本兼容性与资源检查，Tool 1/2/3 复用，Tool 4 真实规划。
3. 面积、坡度和连片度由确定性硬约束校验，不由模型自评。
4. 只有通过结果进入 verified memory，下一任务才能召回。

2026-07-30 锁定路径两次真实运行总耗时为 `93.490s / 112.940s`，末次对应最终代码。现场 70 秒片段必须由
无剪辑母版的等待段加速生成，并标注该母版实际耗时；不得表述为优化引擎实时 70 秒完成。

不要现场展开全部参数，不解释每个 A/B/C/D 内部细节。

## 3. NL2Semantic2GeoSQL 演示

最终只锁定一个问题，优先选择：

```text
@NL2SQL 统计距离道路网络中最长桥梁100米范围内的高德POI数量。
```

画面必须同时出现：自然语言问题、关键 `ST_DWithin(...::geography, 100)`、只读执行结果 `35`。口播只解释空间距离单位和 schema grounding，不现场读 SQL。

## 4. 异常恢复视频

异常分支不在主现场故意触发，单独准备 35–45 秒视频：

```text
status -> inspect -> recall -> pipeline
-> audit(attempt=0, retryable=true)
-> plan -> audit(attempt=1) -> commit
```

再准备 15 秒版本阻断片段：

```text
status(version incompatible) -> inspect -> stop
```

它证明 Agent 会安全停止，不会为了完成目标伪造成功。

## 5. 赛前 60 分钟检查

- 运行 `scripts/check_gemma4_finals_preflight.py`，确认 `ready=true`。
- `docker compose ps` 全部 healthy。
- Ollama `Gemma4:26b` 已预热，现场不再拉模型。
- NL2SQL 数据库快照固定，结果与视频一致。
- 县域耕地优化成功产物、6 工具轨迹、地图和图文 PDF 均已打开到浏览器标签。
- 本地视频使用 H.264 MP4，1080p，离线可播放。
- PPT、MP4、关键截图各保留本机和 U 盘副本。
- 关闭通知、同步盘弹窗、自动更新和屏幕休眠。
- 浏览器缩放和系统字体在投影仪上可读。

## 6. 故障切换

| 故障 | 5 秒内动作 | 口播 |
|---|---|---|
| 模型首 token 超过 8 秒 | 立即切到成功链视频 | “这里切到同版本预录轨迹，完整参数与结果均保留在运行日志。” |
| 县域优化工具运行失败 | 切到真实运行产物和 verified episode | “现场不重试高成本规划，展示已封存的同版本真实产物。” |
| 数据库不可用 | 切 NL2SQL 结果视频 | “该片段使用固定数据库快照，SQL 和执行结果可复核。” |
| 前端空白 | 切 PPT 中的轨迹和地图截图 | 不现场调试 |
| 无网络 | 保持本地 Gemma 4、PostGIS、县域优化引擎离线演示 | “核心链路不依赖公网。” |

## 7. 禁止事项

- 不现场运行十小时级完整训练。
- 不故意制造不可控错误。
- 不用应用层 fallback 冒充 Gemma 工具调用。
- 不把 30/30 编排评测说成算法重跑。
- 不把 GWM 领域原型说成完整通用 GWM，也不把 MPC 本身说成世界模型。
- 不说 v2.2.3 已完成部内生产验证。
- 不在主 5 分钟展开 AlphaEarth 或 OKF；只在 Q&A/附录回答。
