# TWM 对 GeoSOS DongGuan 80m 教程数据的可行性判断

更新日期：2026-06-21

本文回答一个非常具体、也非常容易被客户追问的问题：

> `/Users/zhouning/Downloads/1TutorialData_DongGuan_80m.zip` 这份原来给 GeoSOS/FLUS 用的 DongGuan 80m 测试数据，TWM 能不能基于它做模拟和优化分析？TWM 的 simulator 和 planner 能不能实现或者超越 GeoSOS 以前的效果？

结论先行：

- 能做，但不是开箱即用。
- 这份数据很适合做 GeoSOS/FLUS 风格的土地利用变化模拟对照实验。
- 当前 TWM 不能直接把这个原始 ZIP 当成原生输入跑完整 TWM 世界模型闭环，需要一个适配层。
- 如果问题是“能不能复现土地利用模拟”，答案是：可以做验证版，需要补一个 raster/transition adapter 或专门 backend。
- 如果问题是“现在是否已经证明超过 GeoSOS/FLUS”，答案是：不能这样承诺，必须跑对照实验。
- 如果问题是“在自然资源治理工作流里，TWM 有没有机会超过 GeoSOS”，答案是：有，而且重点不在单纯地类模拟精度，而在规则、证据、反事实、方案比选和审计闭环。

## 1. 给客户的短答案

### 1.1 30 秒版本

这份 DongGuan 80m 数据可以给 TWM 用，但需要先做一次格式和语义适配。它天然适合做 GeoSOS/FLUS 式土地利用变化模拟基线，不适合直接支撑 TWM 的完整治理型世界模型。  
所以，如果客户问“能不能做”，答案是能做验证；如果问“现在是否已经超过 GeoSOS”，答案是不能无证据承诺，必须跑同口径 benchmark。

### 1.2 适合自然资源用户的口径

更准确的说法不是“ TWM 直接替代 GeoSOS”，而是：

> 这份数据原来主要服务于土地利用格局模拟；TWM 可以把它转成自己的实验输入，用来做地类变化预测和方案比选验证。但如果要发挥 TWM 真正强项，还需要再补规划边界、项目、规则、证据和审批监管类数据。

## 2. 这份数据本身是否合格

答案是合格，而且是很典型的 GeoSOS/FLUS 教程型数据包。

已核验到的数据内容包括：

- 行政边界：`Boundary/DongGuan.*`
- 三期土地利用栅格：`landuse2000.tif`、`landuse2005.tif`、`landuse2006.tif`
- 地类配置：`Config Files/DefaultLanduseInfo.xml`
- 转换约束矩阵：`Config Files/SuitableMatrix.xml`
- 驱动因子栅格：
  - `Variables Data/dtcity`
  - `Variables Data/dtfreeway`
  - `Variables Data/dtrailway`
  - `Variables Data/dtroad`

这套结构正好满足传统 FLUS 类实验的基本要件：

1. 历史土地利用状态
2. 后续验证期土地利用状态
3. 多个空间驱动因子
4. 地类定义与转换约束

也就是说，从“做土地利用变化模拟对照实验”的角度，它是适合的。

## 3. 数据技术画像

### 3.1 栅格基本信息

- 空间分辨率：`80m`
- 栅格尺寸：`946 x 648`
- 投影：`Krasovsky_1940_Albers`
- 像元面积：`0.64 ha`
- nodata：文件元数据读到 `0.0`

### 3.2 地类体系

`DefaultLanduseInfo.xml` 中共有 6 类：

| 编码 | 中文 | 英文 |
|---|---|---|
| 1 | 耕地 | Arable Land |
| 2 | 林地 | Woodland |
| 3 | 草地 | Meadow |
| 4 | 水域 | Water |
| 5 | 城乡建设用地 | Construction Land |
| 6 | 未利用地 | Unused Land |

其中：

- 可转类型：`1, 3, 6`
- 不可转类型：`4, 2`
- 城镇建设类型：`5`

`SuitableMatrix.xml` 也给出了可转换矩阵，这对复现 FLUS/GeoSOS 的地类分配逻辑很关键。

### 3.3 数据变化强度

从已核验结果看，这份数据不是“静态摆设”，而是有明显变化信号：

- `2000 -> 2005`：
  - 有效像元：`613008`
  - 变化像元：`100592`
  - 变化比例：`16.41%`
  - 变化面积：`64378.88 ha`
- `2005 -> 2006`：
  - 有效像元：`613008`
  - 变化像元：`21306`
  - 变化比例：`3.48%`
  - 变化面积：`13635.84 ha`

主要变化方向也很典型，尤其是：

- `1 -> 5` 耕地转建设用地
- `2 -> 5` 林地转建设用地

这说明它适合拿来做“城市扩张/土地利用变化”的历史拟合与验证。

## 4. 为什么当前 TWM 不能直接读取这份 ZIP

核心原因不是数据坏，而是输入契约不同。

当前 TWM 的状态构建入口是 MMFE/TWM 语义包，而不是原始 GeoSOS 教程 ZIP：

- `data_agent/territory_world_model/state_builder.py`
- `data_agent/territory_world_model/semantic_loader.py`

从实现上看，当前 `StateBuilder.build_from_bundle()` 会先加载语义包和状态契约，而不是直接读 FLUS 风格的原始栅格目录。`semantic_loader.py` 也默认寻找：

- `twm_mmfe_semantic_product.json`
- `semantic_product.json`
- `twm_state_input_contract.json`
- `twm_state_input.json`

而这份 DongGuan 80m ZIP 并不包含这些 TWM/MMFE 侧的语义与契约文件。

另外，当前 `load_state_source()` 主要支持：

- 表格
- `geopandas` 可读取的矢量地理数据

它并不是一个“原生多期土地利用 raster CA 数据装载器”。  
所以准确说法应该是：

> 不是 TWM 不能用这份数据，而是当前 TWM 还没有内置一个 GeoSOS/FLUS tutorial ZIP -> TWM state/backend 的直连适配器。

## 5. 这份数据能支撑 TWM 做什么

### 5.1 能支撑的部分

如果把目标限定在“土地利用模拟和方案对比验证”，这份数据能支撑：

1. **FLUS 风格模拟基线**
   - 用 `2000 -> 2005` 学习
   - 用 `2005 -> 2006` 验证

2. **TWM 模拟器的实验输入**
   - 把 raster cell 或聚合网格块转成 TWM 的 pseudo-object / token
   - 把驱动因子转成状态特征
   - 把地类转换矩阵转成 transition constraint

3. **TWM 规划器的候选方案比选**
   - 紧凑扩张
   - 耕地保护优先
   - 沿交通走廊发展
   - 受限转换策略
   - 基线不干预策略

### 5.2 不能直接支撑的部分

但这份数据本身不能直接支撑 TWM 的完整治理型能力，因为它缺少以下要素：

- 项目边界
- 规划分区
- 永久基本农田
- 生态保护红线
- 城镇开发边界
- 审批记录
- 执法/监管记录
- 证据索引
- 复核任务

所以，如果只给这份 GeoSOS 教程数据，那么 TWM 的优势会被压缩成“变化模拟和目标优化实验”，而不是完整的“自然资源治理世界模型”。

## 6. TWM 的 simulator 能不能实现 GeoSOS/FLUS 的效果

### 6.1 可以做，但要分层回答

这个问题不能简单回答“能”或“不能”，要分成三层。

#### 第一层：数据上能不能做

能。  
这份数据具备做 FLUS 类实验的必要条件，完全可以用于：

- 历史变化学习
- 未来一期预测
- 地类转换评估
- 情景约束实验

#### 第二层：当前代码是否已经开箱即用支持

不能。  
当前 TWM 还没有把这类 GeoSOS 栅格教程包直接接成原生模拟器输入。

#### 第三层：通过适配后能不能达到同类效果

可以作为研发目标，但不能先验承诺已经达到。

更准确地说：

- 如果补的是 **raster CA / transition backend**，TWM 有机会复现 FLUS 类地类变化实验；
- 如果补的是 **对象化聚合输入 + 现有 TWM dynamics backend**，也可以做，但这更偏研究路线，不应直接承诺与 FLUS 同精度。

### 6.2 当前 TWM simulator 的现实边界

当前仓库里的 TWM simulator 已经具备原型闭环，包括：

- action-conditioned forecast
- counterfactual rollout
- uncertainty metadata
- 多个 candidate backend

见：

- `data_agent/territory_world_model/service.py`
- `data_agent/territory_world_model/neural_dynamics.py`
- `docs/twm-current-handoff.md`

但仓库内文档也明确承认，当前实现仍是：

> rigorous scaffold/candidate implementation，而不是最终生产级 territorial world model

这句话的含义很重要：  
它说明现在已经有“能跑的 world-model 原型”，但还没有证据表明它在 DongGuan 80m 这种 FLUS 标准任务上，已经稳定超过 FLUS。

## 7. TWM 的 planner 能不能做优化分析

答案是能，但要看“优化”定义成什么。

### 7.1 如果把优化理解为 GeoSOS 式地类分配优化

能做实验版，但同样需要先补适配层和目标函数。

这份数据可以支持的优化目标包括：

- 建设用地增长目标
- 耕地损失最小化
- 禁止转换约束
- 紧凑度/连通性目标
- 交通导向发展偏好

从这个意义上说，TWM planner 可以做“多目标方案比选”，不是完全做不了。

### 7.2 如果把优化理解为 TWM 式治理型规划器

仅靠这份数据还不够。

当前 TWM planner 的强项并不只是“找一个分配结果”，而是消费 simulator 输出，综合：

- utility
- risk
- confidence
- action mask
- evidence gate

然后做候选方案排序与反事实比较。

但这些治理向能力，需要项目、规则、证据、审批等额外数据才能真正发挥。  
只用 DongGuan 80m 教程数据，planner 的发挥空间会被限制在“土地利用情景比选”。

## 8. 能不能说 TWM 超越 GeoSOS/FLUS

### 8.1 在纯土地利用模拟精度上

现在不能这么说。

原因很简单：

- 还没有完成同口径 benchmark
- 还没有跑 `2000 -> 2005` 训练、`2005 -> 2006` 验证
- 还没有输出 OA、Kappa、FoM、类面积误差、城市扩张 precision/recall 等指标

在没有这些结果前，任何“已经超过 FLUS”的说法都不稳。

### 8.2 在自然资源治理能力上

可以说 TWM 的能力上限更高，但前提是补齐治理数据。

TWM 真正可能超越 GeoSOS/FLUS 的地方不是一句“预测更准”，而是下面这些能力组合：

| 维度 | GeoSOS/FLUS | TWM |
|---|---|---|
| 土地利用变化模拟 | 强 | 可做，但需适配与验证 |
| 地类分配/情景实验 | 强 | 可做 |
| 项目-规则-证据联动 | 不是核心 | 强项 |
| 反事实推演 | 有限 | 强项 |
| 人工复核门控 | 有限 | 强项 |
| 审计留痕 | 有限 | 强项 |
| 规划 claim 的证据升级边界 | 有限 | 强项 |

所以更稳妥的表达是：

> 在“像素级土地利用模拟精度”这个单点上，TWM 不能未经实验就宣称超过 FLUS；但在“自然资源治理闭环”这个更大任务上，TWM 的目标明显比 GeoSOS/FLUS 更宽，理论上也更有机会超越其业务效果。

## 9. 最适合的工程落地方式

如果要把这份数据真正接到 TWM 上，建议走两阶段。

### 9.1 阶段 A：先复现 FLUS 风格基线

目标是先回答：

> TWM 至少能不能在这份数据上做出一个可比较的 land-use simulation baseline？

建议做法：

1. 读取 `landuse2000.tif`、`landuse2005.tif`、`landuse2006.tif`
2. 读取四个驱动因子 raster
3. 解析 `DefaultLanduseInfo.xml` 和 `SuitableMatrix.xml`
4. 用 `2000 -> 2005` 建模
5. 用 `2005 -> 2006` 做验证
6. 输出同口径评价指标

### 9.2 阶段 B：再接入 TWM 的 simulator + planner

两种路线都可行：

#### 路线 1：保留 raster 语义，给 TWM 挂一个专门 backend

优点：

- 最接近 FLUS 对比口径
- 对纯土地利用模拟最公平

缺点：

- 与现有对象-关系式 TWM 状态接口耦合较弱

#### 路线 2：把 raster 聚合成对象化状态，再走 TWM 原生路线

优点：

- 更接近 TWM 长期架构
- 更容易接后续规划规则和治理数据

缺点：

- 与 FLUS 做“像素级精度对标”时不完全同口径

实际工程上，最合理的是两条都做：

- 一条保底复现基线
- 一条验证 TWM 自身路线

## 10. 推荐 benchmark 设计

### 10.1 对比对象

- GeoSOS/FLUS baseline
- TWM-raster adapter baseline
- TWM-object/hierarchical simulator candidate

### 10.2 评价指标

建议至少包含：

- Overall Accuracy, OA
- Kappa
- Figure of Merit, FoM
- 各地类面积误差
- 转换矩阵误差
- 城市扩张 precision / recall
- 紧凑度或连通性指标
- 受限转换违规率

### 10.3 业务型补充指标

如果要体现 TWM 的优势，不能只看地图精度，还应增加：

- 方案可解释性
- 约束冲突暴露能力
- 候选方案排序稳定性
- 不确定性表达
- 证据链完整性
- 是否能明确标记 review required

## 11. 对外宣讲时哪些话能说，哪些话不能说

### 11.1 可以说

- 这份 DongGuan 80m 数据可以作为 TWM 对标 GeoSOS/FLUS 的标准实验数据。
- TWM 可以基于该数据做模拟和优化验证，但需要适配层。
- 这份数据足以验证 TWM 在土地利用变化模拟和方案比选上的可行性。
- 如果补齐治理型数据，TWM 能把传统土地利用模拟扩展到规则、证据、审计和复核闭环。

### 11.2 不建议说

- TWM 现在已经开箱即用读取 GeoSOS 教程 ZIP。
- TWM 已经证明在 DongGuan 80m 上超过 FLUS。
- TWM 可以只靠这份教程数据完成完整自然资源审批审查结论。

## 12. 最终判断

最终可以给出一个非常清楚的判断：

> 这份 GeoSOS DongGuan 80m 教程数据，TWM 能用，而且很适合拿来做 FLUS 对照实验；但当前不能直接原样接入，需要一个适配层。  
> TWM 的 simulator 和 planner 有能力在这份数据上做模拟与方案优化验证，但如果问“现在是否已经在土地利用模拟效果上超过 GeoSOS/FLUS”，答案是还不能无证据承诺，必须先跑同口径 benchmark。  
> 真正体现 TWM 优势的方向，不是单纯地类变化图，而是把模拟结果进一步纳入规则、证据、反事实和审计闭环，服务自然资源治理场景。

## 13. 相关依据

### 13.1 外部依据

- GeoSOS 首页：`http://www.geosimulation.cn/index.html`
- FLUS 页面：`http://www.geosimulation.cn/FLUS.html`
- 论文：`/Users/zhouning/Downloads/2017LUP-FLUS.pdf`
- 论文：`/Users/zhouning/Downloads/A Geographical Simulation and Optimization System Based on Coupling Strategies.pdf`

### 13.2 本地代码与文档依据

- `data_agent/territory_world_model/state_builder.py`
- `data_agent/territory_world_model/semantic_loader.py`
- `data_agent/territory_world_model/service.py`
- `docs/twm-current-handoff.md`
- `docs/twm-vs-geosos-flus-comparison.md`
- `docs/twm-vs-geosos-flus-academic-positioning.md`
- `docs/twm-vs-geosos-flus-user-explanation.md`

