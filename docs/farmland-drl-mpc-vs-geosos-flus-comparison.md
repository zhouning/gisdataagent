# 耕地空间布局优化中 Paper1-4 与 Paper9 相对 GeoSOS/FLUS 的比较

更新日期：2026-06-21

本文专门回答如下问题：

> 在耕地空间布局优化场景中，Paper1 到 Paper4 使用的无模型或弱模型深度强化学习方法，以及 Paper9 使用的有模型 world model / MPC 方法，与 GeoSOS/FLUS 相比到底如何？

这份文档不讨论一般意义上的土地利用变化模拟，而是聚焦：

- 耕地与林地的置换优化
- 耕地坡度下降
- 连片度提升
- 百亩方数量提升
- 保持耕地数量或面积平衡
- 乡镇到县域尺度的连续决策与方案比选

## 1. 先给结论

一句话结论：

> 如果任务是“耕地空间布局优化”，那么 Paper1-4 与 Paper9 这条方法线比 GeoSOS/FLUS 更对题；其中，无模型 DRL 证明了问题可学，而 Paper9 这种有模型规划路线更接近当前这条技术线的成熟形态。

更细一点：

- **GeoSOS/FLUS** 更适合宏观多地类土地利用变化模拟与情景分配；
- **Paper1-4** 更适合把耕地布局问题写成显式目标与约束下的序列优化；
- **Paper9** 在此基础上进一步把问题做成 learned surrogate + MPC，更适合高分支离散动作空间下的快速规划与反复重规划。

因此，不建议简单说：

> Paper9 比 FLUS 更先进，所以可以替代 FLUS。

更准确的说法是：

> 在耕地空间布局优化这个特定任务上，Paper1-4/Paper9 的问题设定比 GeoSOS/FLUS 更贴合业务目标；但在宏观多地类土地利用变化模拟上，GeoSOS/FLUS 仍然更自然。

## 2. 本文对 Paper1-4 的编号假设

目前本地仓库里能直接核验到的独立主仓库和材料包括：

- `farmland-drl-optimization/`
- `paper3-block-level-farmland-drl/`
- `paper4-county-marl-farmland-consolidation/`
- `arcgis-farmland-mpc/`

其中：

- `paper3` 和 `paper4` 的定位是明确的；
- `paper9` 的定位也是明确的；
- `paper1` 和 `paper2` 没有在当前工作区中以独立仓库完整出现，但后续代码和基准中对其有明确引用。

因此，本文按以下方式理解 `paper1-4`：

1. **Paper1**：较早期 planning-unit / parcel-scoring 无模型 DRL 路线的原型或工具箱阶段；
2. **Paper2**：以 global greedy / GA / 规则式优化为代表的早期强基线阶段；
3. **Paper3**：block-level DRL；
4. **Paper4**：county-level centralized DRL / MARL；
5. **Paper9**：contrastive learned world model + MPC。

这个假设若与作者内部编号略有差别，会影响表述精细度，但不会改变核心比较结论。

## 3. 几类方法各自在解决什么问题

### 3.1 GeoSOS / FLUS

GeoSOS/FLUS 主要解决的问题是：

- 多地类土地利用变化模拟
- 城市扩张
- 未来情景推演
- 用地需求驱动下的空间分配
- CA / ANN / 邻域竞争机制下的地类演化

它更像在回答：

> 在驱动因子、情景设定和约束条件下，未来土地利用格局会怎么变？

### 3.2 Paper1-4 无模型或弱模型 DRL 线

这条线主要解决的问题是：

- 在固定预算下换哪些地块或区块
- 怎样降低耕地平均坡度
- 怎样提高连片度
- 怎样形成更多百亩方
- 怎样保持耕地数量或面积平衡
- 怎样从单村扩展到跨乡镇、跨县域协调

它更像在回答：

> 在明确的目标函数和约束下，下一步应该换哪里，持续换多少步，才能得到更优的耕地布局？

### 3.3 Paper9 有模型规划线

Paper9 的核心不是直接学一个最终策略，而是：

1. 先学一个 surrogate dynamics / reward model；
2. 再用 MPC 在候选动作中做 lookahead 和 ranking；
3. 反复选出当前最优动作。

它回答的问题更像：

> 如果在当前状态下尝试这些候选交换动作，短期未来会怎样变化？哪个动作序列最值得执行？

## 4. 为什么在耕地布局优化上，Paper1-4 / Paper9 比 GeoSOS/FLUS 更对题

核心原因是任务对象不同。

GeoSOS/FLUS 的天然对象是：

- 栅格
- 多地类
- 驱动因子
- 需求分配
- 邻域扩张

而耕地空间布局优化这条 paper 线的天然对象是：

- 图斑或规划单元
- 耕地/林地成对置换
- 坡度
- 邻接连片
- 百亩方阈值
- 预算与执行约束

也就是说：

- FLUS 关心“未来地类格局怎么演化”
- Paper1-4 / Paper9 关心“现在该怎么改图斑布局”

这是本质区别。

如果一定要比喻：

- **FLUS** 更像“推演未来地图”
- **Paper1-4 / Paper9** 更像“直接给出改图方案”

## 5. 无模型 DRL 相对 GeoSOS/FLUS 的优势与不足

### 5.1 优势

无模型 DRL 相对 GeoSOS/FLUS 的最大优势，是目标函数表达更直接。

在耕地布局优化中，常见目标包括：

- 最小化耕地平均坡度
- 最大化耕地连片度
- 增加百亩方数量
- 维持耕地面积平衡
- 控制交换预算

这些目标在 DRL 中可以直接写进 reward 或 constraint，而不需要绕回到多地类 CA 分配逻辑。

因此，无模型 DRL 的优势主要体现在：

- 任务目标贴合
- 行动定义清楚
- 易于显式编码约束
- 适合序列决策
- 适合做单村、乡镇、县域级布局优化

### 5.2 不足

无模型 DRL 也有非常明显的代价：

- 训练成本高
- seed 敏感
- 稳定性依赖超参数
- 一旦目标权重变化，往往需要重训
- 泛化能力通常不如表面看起来那么强
- 解释性弱于规则或模型驱动方法

从本地仓库证据看，这些不足都是真实存在的：

- `farmland-drl-optimization/README.md` 明确把该路线定位为 **two-site proof of concept**，不是普遍跨区泛化主张；
- `paper3` 把自己定位为 **scenario screening**，不是“RL 全面压倒启发式”；
- `paper4` 的训练代价已经达到每 seed 约 `8-12` 小时 A100 级别。

所以更准确的评价是：

> 无模型 DRL 在耕地布局优化上比 FLUS 更贴题，但并不意味着工程上更轻、更稳、更容易落地。

## 6. Paper3：Block-level DRL 的位置

`paper3-block-level-farmland-drl/README.md` 的定位非常清楚：

> Policy-Relevant Block Abstraction for Sequential Farmland Consolidation Scenario Screening

这说明 Paper3 的核心价值是：

- 把原始图斑聚合为 block
- 降低动作空间复杂度
- 适合做前期方案筛选
- 更面向政策比较和 scenario screening

同时，`src/baselines_block.py` 里明确写到：

- `Greedy-Global` 是 **Paper 2 baseline**
- `Greedy-Sequential`
- `Random-Block`
- `Round-Robin`

这表明 Paper3 并不是脱离传统优化，而是在更公平的 block-level 任务口径下，与早期 global greedy 等方法竞争。

因此，Paper3 相对 FLUS 的评价是：

- **强于 FLUS 的地方**：更像真实耕地整治优化任务；
- **弱于 FLUS 的地方**：不是为了做大尺度多地类演化模拟。

Paper3 的最佳定位不是“替代 FLUS”，而是：

> 面向耕地整治场景的 block-level sequential optimization framework。

## 7. Paper4：County-level centralized DRL / MARL 的位置

`paper4-county-marl-farmland-consolidation/README.md` 显示，Paper4 已经把问题从单乡镇/单块抽象推进到县域跨乡镇协调。

其关键特征包括：

- County-level environment
- Centralized DRL
- MARL with parameter sharing
- Cross-township coordination

README 给出的结果也说明：

- centralized DRL 与 MARL 的均值 slope reduction 接近；
- MARL 的 cross-seed 波动更小。

这说明 Paper4 的真正贡献不是简单“分数更高”，而是：

- 把优化尺度扩大到县域
- 让多主体协调成为问题的一部分
- 让“跨乡镇布局协调”成为可学习对象

相对 GeoSOS/FLUS，Paper4 的优势很明显：

- 更贴合县域耕地整治的行动结构
- 能处理跨乡镇协调
- 目标函数更接近业务考核

但问题也更明显：

- 训练成本进一步上升
- 运行和复现实验成本明显高于 FLUS
- 还是典型无模型 RL 的稳定性与解释性问题

因此，Paper4 可以理解为：

> 把无模型 DRL 路线从“局部可行”推进到“县域可组织”，但仍未完全解决无模型 RL 在工程上昂贵和不稳的问题。

## 8. Paper9：有模型 world model / MPC 路线为什么更强

`arcgis-farmland-mpc/README.md` 给出的定位是：

> Reproducible model-based planning for county-scale farmland consolidation

这条路线与 Paper1-4 的最大不同，是它不再只是直接学 policy，而是：

- 学一个 transition / reward surrogate
- 用 ensemble 提高鲁棒性
- 用 MPC 做短视野规划与动作排序
- 在分钟级时间内反复跑候选方案

本地文档 `notes/world_model_comparison.md` 也明确指出：

> Paper9 的 "world model" 更接近 Chua 2018 / Janner 2019 这条窄义 model-based RL，而不是 Dreamer 式表征学习世界模型

这点很重要。它说明 Paper9 的价值不在“概念更潮”，而在：

- 把高分支离散空间里的动作排序问题做对了；
- 把 RL 的训练成本问题转化为 surrogate 学习 + planning；
- 在保留优化质量的同时，提高了重规划效率。

### 8.1 相对无模型 DRL 的优势

Paper9 相对无模型 DRL 的优势主要有：

- 更适合 repeated planning
- 更适合 what-if 分析
- 更适合 reward-weight sensitivity
- 重跑不同策略时不必每次都完整重训 policy
- 更容易做 action ranking 和 candidate comparison

### 8.2 相对 GeoSOS/FLUS 的优势

Paper9 相对 FLUS 的优势则是：

- 更直接服务耕地整治行动
- 更适合图斑/区块/县域离散交换
- 更适合显式 no-net-loss 和执行约束
- 更适合短期执行方案规划，而不只是趋势模拟

### 8.3 不能夸大的地方

但 Paper9 也不能被表述成“全面超越 FLUS”，因为：

- 它不以多地类长期格局演化为核心任务；
- 它的 world model 是任务特定 surrogate，不是通用土地利用变化模型；
- 换到宏观区域 LUCC 情景推演问题，FLUS 仍然更自然。

## 9. 现有本地证据支持的排序判断

如果只看“耕地空间布局优化”这个任务，我的判断排序如下：

### 第一梯队：Paper9 有模型规划

原因：

- 任务贴合度最高
- 规划与重规划能力最强
- 更容易做候选方案对比
- 比无模型 DRL 更像“可运行的规划器”

### 第二梯队：Paper4 县域 centralized / MARL 无模型 DRL

原因：

- 已经把问题推进到县域尺度
- 说明跨乡镇协调是可学的
- 但训练成本和不稳定性仍然偏高

### 第三梯队：Paper3 block-level DRL

原因：

- 非常适合 scenario screening
- 在 policy-facing 比选场景里有明确价值
- 但更像筛选器而不是最终县域级生产规划器

### 第四梯队：Paper1/早期 planning-unit 无模型 DRL 线

原因：

- 证明 RL 在这个任务上可行
- 对小范围单点优化很有价值
- 但更偏 proof-of-concept 或早期 operational route

### 基线与外部参照：GeoSOS/FLUS

原因：

- 是强外部土地利用模拟基线
- 适合作为宏观变化情景参照
- 不是最自然的耕地-林地离散交换优化器

## 10. 与 GeoSOS/FLUS 比，真正该怎么讲

面向客户、评审或答辩时，不建议说：

> 我们的方法比 FLUS 更先进，所以能替代 FLUS。

更稳妥的说法应该是：

> FLUS/GeoSOS 擅长多地类土地利用变化模拟与情景推演；Paper1-4/Paper9 这条方法线擅长耕地空间布局优化和离散交换决策。两者不在同一个任务中心上竞争。对耕地布局优化而言，Paper1-4/Paper9 更贴题；对宏观土地利用变化模拟而言，FLUS 仍然是更自然的传统基线。

## 11. 一个面向自然资源用户的通俗版本

如果用最通俗的话说：

- `GeoSOS/FLUS` 更像是在看：
  - “未来地图会怎么变”
- `Paper1-4` 更像是在做：
  - “一步一步学着改布局”
- `Paper9` 更像是在做：
  - “先学会预判改了会怎样，再从很多方案里挑最值得改的”

因此，在耕地空间布局优化这件事上：

> Paper9 最像一个真正的规划器；Paper1-4 是这条规划器路线逐步长出来的前几代；GeoSOS/FLUS 更像外部情景模拟参照，而不是最对题的核心优化器。

## 12. 最终结论

最终结论可以概括为三句话：

1. **在耕地空间布局优化场景中，Paper1-4 与 Paper9 比 GeoSOS/FLUS 更对题。**
2. **无模型 DRL 证明了这个问题可以通过序列决策学习来做，但代价是训练重、稳定性一般。**
3. **Paper9 的有模型规划路线目前更像这条技术线的成熟形态，因为它在优化质量、重规划效率和任务贴合度之间取得了更好的平衡。**

## 13. 本文依据

### 13.1 本地仓库依据

- `farmland-drl-optimization/README.md`
- `paper3-block-level-farmland-drl/README.md`
- `paper3-block-level-farmland-drl/src/baselines_block.py`
- `paper4-county-marl-farmland-consolidation/README.md`
- `paper4-county-marl-farmland-consolidation/src/train_county.py`
- `arcgis-farmland-mpc/README.md`
- `arcgis-farmland-mpc/notes/world_model_comparison.md`
- `arcgis-farmland-mpc/benchmark/baselines/run_ga.py`
- `arcgis-farmland-mpc/benchmark/baselines/run_ppo.py`

### 13.2 外部参照依据

- GeoSOS 首页：`http://www.geosimulation.cn/index.html`
- FLUS 页面：`http://www.geosimulation.cn/FLUS.html`
- `2017LUP-FLUS.pdf`
- `A Geographical Simulation and Optimization System Based on Coupling Strategies.pdf`

