# Data Agent 架构评审与重构计划书

## 1. 综述
本项目是一个基于 `google.adk` 框架的专业 GIS 数据智能体平台。经过深度代码审计，系统在多智能体编排（Multi-Agent Orchestration）和工具链抽象上表现优秀，但在工程化实现、模块解耦及跨环境兼容性策略上仍有优化空间。

---

## 2. 架构评审 (Architecture Review)

### 2.1 核心优势
- **编排模式成熟**：有效利用了 `ParallelAgent` 进行任务并发，以及 `LoopAgent` 构成的 Generator-Critic 闭环。
- **业务领域隔离**：`toolsets/` 的分包策略清晰，GIS 业务逻辑与智能体外壳解耦良好。
- **企业级基座**：具备完善的审计、RBAC、多语言和可观测性设计。

### 2.2 待改进项
- **单一入口臃肿**：`app.py` 承载了过多的职责（超过 3500 行），违背了单一职责原则，增加了维护难度。
- **配置与逻辑耦合**：智能体的 Prompt 和运行策略硬编码在 Python 代码中，不利于生产环境的热调优。
- **依赖管理碎片化**：大量单例服务（OBS, Bots, DB）在各处初始化，缺乏统一的依赖注入管理。

---

## 3. 关键设计建议：双引擎 GIS 抽象层

针对项目“开源优先、ArcPy 可选”的核心定位，建议实施以下重构策略：

### 3.1 引入 `GISEngine` 策略模式
不应在工具类中直接调用 `import arcpy` 或 `import geopandas`，而是通过抽象基类定义接口。

- **接口定义**：定义通用的 `SpatialOperation` 接口（如剪裁、缓冲、叠加分析）。
- **开源引擎 (Default)**：基于 `GeoPandas`, `Shapely`, `GDAL/OGR` 实现。
- **ArcPy 引擎**：基于 `ArcPy` 实现，仅在特定环境/配置下激活。

### 3.2 优先级切换逻辑
在初始化时，通过环境变量或配置文件（如 `.env` 中的 `GIS_BACKEND_PRIORITY`）决定加载顺序：
1. **默认路径**：系统自检环境，优先尝试加载开源依赖。
2. **强制路径**：当客户指定 `REQUIRE_ARCPY=true` 时，系统验证 `arcpy` 授权，若不满足则报错提示。

---

## 4. 代码重构行动清单 (Refactoring Roadmap)

### 第一阶段：核心解耦 (High Priority)
- [ ] **拆分 `app.py`**：
    - 迁移 Auth 逻辑到 `data_agent/auth.py`。
    - 迁移 API 路由到 `data_agent/api/` 目录。
    - 迁移 UI 组件逻辑到 `data_agent/ui/components.py`。
- [ ] **完善 `ServiceRegistry`**：
    - 建立统一的单例管理容器，管理数据库连接池、对象存储客户端和消息机器人实例。

### 第二阶段：配置驱动化 (Medium Priority)
- [ ] **Prompt 外置化**：将 `agent.py` 中硬编码的 `system_instruction` 全部迁移至 `prompts.yaml`。
- [ ] **Agent 模板化**：支持通过配置文件定义智能体的参数（Temperature, Model, Tools），实现“配置即 Agent”。

### 第三阶段：GIS 引擎标准化 (Structural Change)
- [ ] **重构 `toolsets/` 内部实现**：
    - 将 `arcpy_tools.py` 中的逻辑重构为 `GISEngine` 接口的一个具体实现。
    - 补齐开源引擎的地理处理能力，确保在无 `arcpy` 环境下的核心功能可用性。

---

## 5. 结论
通过上述重构，`Data Agent` 将从一个强绑定特定 GIS 环境的工具转变为一个**环境无关 (Environment Agnostic)** 的智能化分析平台，显著提升其在不同客户现场的部署灵活性。
