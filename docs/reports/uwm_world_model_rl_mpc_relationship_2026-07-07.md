# UWM 中 World Model、强化学习与 MPC 的关系

日期：2026-07-07

## 1. 一句话结论

- 强化学习 RL：研究智能体如何通过行动最大化长期回报。
- World Model：研究智能体如何在内部构建一个可预测、可模拟、可用于规划的环境模型。
- Model-free RL：不显式构建环境模型，直接学习策略或价值函数。
- Model-based RL：显式使用环境模型做模拟、规划或训练。
- MPC：一种基于模型的滚动规划控制方法，可以作为 model-based RL 的 planner，也可以独立于 RL 使用。

## 2. World Model 和强化学习的区别

强化学习的核心对象是：

```text
state -> action -> reward -> next state
```

目标是学到一个策略：

```text
policy: state -> action
```

使长期累计 reward 最大。

World Model 的核心对象不是策略本身，而是环境内部机制：

```text
当前状态 + 行动 -> 未来状态 / 奖励 / 风险 / 观测
```

也就是学习或构建一个内部模拟器：

```text
world_model(s, a) -> s', r, uncertainty
```

因此二者的区别是：

```text
RL 是决策学习框架；
World Model 是支撑决策的环境模拟与预测机制。
```

World Model 可以服务于 RL，但不等于 RL。在 UWM 城市宜居性分析中，World Model 可以用于宜居性模拟、空间外溢预测、政策方案推演、风险评估和反事实分析，即使某一阶段暂时不训练 RL policy，也仍然是世界模型架构的一部分。

## 3. World Model 和 Model-Free RL 的关系

Model-free RL 不显式学习环境转移模型。

典型算法包括：

```text
DQN
PPO
A2C / A3C
SAC
DDPG
TD3
```

它们主要学习：

```text
Q(s, a)
V(s)
policy(a | s)
```

但不要求显式学习：

```text
P(s' | s, a)
R(s, a)
```

Model-free RL 的优点是形式直接，适合交互样本充足、环境可大量试错的场景。但在城市复杂巨系统中，它有明显问题：

- 样本效率低；
- 不擅长反事实推演；
- 不天然回答“如果我做另一个动作会怎样”；
- 解释性较弱；
- 真实城市政策交互成本高，不能随意试错。

World Model 和 model-free RL 的关系可以概括为：

```text
model-free RL 可以不用 world model；
world model 可以为 model-free RL 生成 imagined experience，提高训练效率。
```

例如 Dreamer 类方法就是先学习世界模型，在 latent imagination 中训练 actor-critic。

## 4. World Model 和 Model-Based RL 的关系

Model-based RL 显式使用模型：

```text
学习/给定环境模型 -> 在模型中模拟 -> 规划或训练策略
```

典型流程是：

```text
real data
 -> learn dynamics / reward / uncertainty model
 -> simulate rollouts
 -> planner or policy optimization
 -> action
```

World Model 通常是 model-based RL 的核心组件，但二者不是完全等价。

```text
Model-based RL 更强调“用模型提高 RL 决策”；
World Model 更强调“构建可模拟、可预测、可解释的环境内部表征”。
```

差异包括：

- model-based RL 可以只使用一个简单 transition table，也仍然是 model-based；
- world model 通常更复杂，包含状态编码、动力学、奖励、观测、空间结构、不确定性、渲染器、模拟器和规划器；
- world model 可以用于 RL，也可以用于规划、仿真、数字孪生、反事实分析和管理决策支持。

在 UWM 场景中，目标不应是随便跑一个 RL 算法，而应是：

```text
构建城市状态表征
+ 构建可解释模拟器
+ 构建空间/机制/不确定性模型
+ 构建规划器
+ 在必要时训练 policy/value network
+ 用同一数据场景证明输出结果超过传统静态方法
```

## 5. MPC 和强化学习的关系

MPC 是 Model Predictive Control，即模型预测控制。

MPC 的基本逻辑是：

```text
当前状态 s_t
 -> 用模型预测未来 H 步
 -> 搜索最优动作序列
 -> 只执行第一个动作
 -> 到下一时刻重新观测，再重新规划
```

形式上可以写成：

```text
argmax a_t...a_t+H  sum reward / utility / objective
```

MPC 本质上是一种 planner 或 controller，不一定是 RL。它可以完全不学习：

```text
已知物理模型 + 优化器 = MPC
```

例如工业控制、自动驾驶轨迹规划、机器人控制中都常见 MPC。

MPC 也可以和 RL 结合：

```text
RL 学模型，MPC 用模型规划；
RL 学 cost/reward，MPC 优化动作；
MPC 生成专家轨迹，RL 模仿；
RL 学 policy，MPC 做安全约束或局部修正。
```

所以二者关系是：

```text
MPC 是一种基于模型的规划/控制方法；
Model-based RL 可以把 MPC 当作 planner；
但 MPC 本身不等于 RL。
```

## 6. 放到 UWM 城市宜居性分析中

传统方法通常是：

```text
指标体系 -> 加权评分 -> 排名 -> 人脑决策
```

它通常没有：

```text
行动后的状态转移模拟
空间外溢模拟
长期回报
反事实比较
策略搜索
不确定性传播
```

UWM 应该是：

```text
renderer：把多源城市数据变成状态
simulator：模拟 action 对城市状态的影响
planner：搜索行动序列
world model / dynamics：预测未来状态和 reward
policy/value model：学习哪些行动更优
```

MPC 在 UWM 中可以作为 planner：

```text
当前城市状态
 -> 模拟未来若干步宜居性变化
 -> 搜索最优干预序列
 -> 输出推荐行动
```

RL 在 UWM 中可以进一步用于：

```text
学习价值函数
学习策略
学习长期回报结构
从大量 imagined rollout 中优化规划能力
```

因此 UWM 更合理的技术定位是：

```text
以 world model 为核心，
以 model-based RL / planning 为决策机制，
MPC 可作为滚动规划器，
model-free RL 不是首选，但可作为策略学习或对照方法。
```

对城市这种复杂巨系统而言，单纯 model-free RL 风险较大，因为真实交互代价高、样本少、政策干预不能随意试错。更适合的是：

```text
真实数据校准 world model
+ simulator 生成反事实 rollout
+ MPC / graph search / model-based RL 做规划
+ 必要时训练 value network
+ 严格用真实 holdout 和同场景传统基线验证
```

## 7. 对当前 UWM 开发的约束

后续 UWM 城市宜居性分析开发必须坚持以下边界：

- 不能把 world model 简化成指标大屏或静态评分。
- 不能把任意 RL 算法运行结果等同于 world model。
- 不能把 simulator-generated rollout 夸大为 observed policy outcome。
- 必须区分 model-free RL、model-based RL、MPC planner 和 world model architecture。
- UWM 的优势应主要体现在传统方法无法输出的最终结果上，例如反事实状态变化、空间外溢、行动序列、风险传播、价值网络证据和规划收益证据。
- 所有 superiority claim 必须基于同一数据基础、同一城市宜居性场景和同一传统基线进行比较。

