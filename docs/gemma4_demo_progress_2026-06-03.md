# Gemma 4 Hackathon Demo Progress - 2026-06-03

## 已完成

- 重新核对 Gemma 4 开发者大赛提交要求：
  - AI Agent 赛道重点：Native Function Calling、多步规划、Memory、Tool Calling 日志。
  - 技术评分重点：模块化架构、深度利用 Gemma 4 函数调用、README/Docker 复现。
  - 私有仓库提交重点：添加 `@gdgreview` 只读权限，截止前固定最后 commit。

- 生成完整演示脚本文档：
  - `docs/gemma4_ai_agent_demo_script.md`

- 确认真实运行依赖：
  - Gemma4:26b Ollama: `http://192.168.25.228:11434`
  - Ollama models:
    - `Gemma4:26b`
    - `nomic-embed-text-v2-moe:latest`
  - Huawei Cloud PostGIS:
    - host: `119.3.175.198`
    - database: `flights_dataset`
    - user: `agent_user`
  - SQLAlchemy 连接已验证通过。

- NL2Semantic2SQL 空间演示用例已真实端到端验证通过：
  - Prompt:
    ```text
    统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量。
    ```
  - Generated SQL:
    ```sql
    SELECT COUNT(DISTINCT b."Id")
    FROM cq_buildings_2021 AS b
    JOIN cq_osm_roads_2021 AS r
      ON ST_INTERSECTS(b.geometry, r.geometry)
    WHERE r.bridge = 'T'
    ```
  - Result:
    ```text
    status=ok
    count=1
    corrections=["semantic_distinct_join_count"]
    ```

- World Model v2.1 真实端到端验证通过：
  - `steps_run=50`
  - `n_blocks=562`
  - `n_selected=50`
  - `total_reward=230.7513`
  - artifacts:
    - `mpc_summary.json`
    - `mpc_land_use.npy`

## 当前注意事项

- `data_agent/.env` 中仍有旧配置，需要录制前确认或覆盖：
  ```text
  OLLAMA_API_BASE=http://192.168.25.228:11434
  EMBEDDING_MODEL=nomic-embed-text-v2-moe
  ```

- 不建议用于视频的 NL2SQL 问题：
  - 普通属性过滤计数：空间特征不够明显。
  - 水田真实面积：当前触发表/几何字段混用问题。
  - 水田与道路相交面积：当前触发 `DLMC/dlmc` 字段别名问题。

- 推荐视频 NL2SQL 用例：
  - 桥梁道路与建筑物轮廓 `ST_INTERSECTS` 空间 join。

## 下一步

1. 录制前在实际系统 UI 中确认：
   - `run_nl2semantic2sql` 工具调用日志可见。
   - `world_model_v21_status` 和 `world_model_v21_plan` 工具调用日志可见。
   - `save_memory` / `recall_memories` 可正常展示。

2. 在 macOS Docker Desktop 机器上验证：
   - `docker compose up -d`
   - README 中一键启动流程是否能复现。
   - 容器内访问 `host.docker.internal` 或显式 LAN IP 的 Ollama 是否正常。

3. 私有仓库提交前检查：
   - README/Docker 指南完整。
   - 技术报告说明 Gemma 4 26B MoE/Ollama 选型理由。
   - 添加 `@gdgreview` 只读权限。
   - 截止前确认最后 commit。
