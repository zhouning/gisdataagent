# Data Agent 开发者指南

## 1. 架构概览
本项目采用 **Chainlit + Google ADK** 双层架构：
*   **前端/交互层**: Chainlit (`data_agent/app.py`)。负责 UI 渲染、事件拦截、多媒体展示。
*   **核心逻辑层**: Google ADK (`data_agent/agent.py`)。负责智能体编排 (`SequentialAgent`)、工具调用、LLM 推理。
*   **工具层**: Python Scripts (`FFI.py`, `drl_engine.py`)。负责具体的 GIS 计算和 DRL 模型推理。

## 2. 目录结构
```text
data_agent/
├── agent.py            # ADK Agent 定义与工具封装 (Core)
├── app.py              # Chainlit 入口 (UI)
├── prompts.yaml        # 智能体 Prompt 集合
├── FFI.py              # 破碎化指数计算引擎
├── drl_engine.py       # 深度强化学习环境 (Gymnasium)
├── report_generator.py # Word 报告生成器
├── test_*.py           # 单元测试与集成测试
└── eval_set.json       # 智能体评估数据集
```

## 3. 开发指引

### 3.1 添加新工具
1.  在 `agent.py` 中编写 Python 函数（如 `def new_tool(file_path: str): ...`）。
2.  在对应的 Agent 定义中注册该工具（如 `tools=[new_tool]`）。
3.  在 `prompts.yaml` 中更新 Agent 指令，告诉它何时使用该工具。
4.  编写单元测试 `test_new_tool.py` 进行验证。

### 3.2 UI 定制
*   修改 `.chainlit/config.toml` 可调整主题、名称、快捷按钮。
*   修改 `app.py` 中的 `extract_file_paths` 可增加新的文件类型预览支持。

### 3.3 运行测试
*   **单元测试**: `python data_agent/test_visualization_agent.py`
*   **端到端测试**: `python -m data_agent.test_end_to_end`
*   **智能体评估**: `python -m data_agent.run_evaluation`

## 4. 依赖管理
项目依赖记录在 `requirements.txt` (根目录)。新增库后请务必更新：
```bash
pip freeze > requirements.txt
```
