# UWM 城市宜居性分析的理论依据、标准依据与结果形态

日期：2026-07-05

## 1. 核心结论

城市宜居性分析有明确的业务理论基础，但它通常不是由某一个单一国家标准完整定义的。与耕地适宜性评价可以直接落到耕地质量、坡度、连片度、耕地保护和土地整治等较稳定指标体系不同，城市宜居性更像一个复合评价与干预框架：

```text
城市宜居性
= 环境健康风险
+ 公共服务可达性
+ 15 分钟生活圈/日常活动便利性
+ 绿地与开放空间
+ 空间公平与环境正义
+ 城市规划可实施约束
```

因此，UWM 城市宜居性分析的理论依据应来自两类来源：

1. 学术理论：健康城市、人居环境质量、环境暴露、公共服务可达性、空间公平、环境正义、15 分钟城市和建成环境-健康关系。
2. 标准/技术文件：环境空气质量、居住区规划、绿地规划、绿色生态城区评价、社区生活圈、城市体检评估等国家标准、工程建设标准和主管部门技术文件。

更准确的表述是：UWM 不是寻找一个“城市宜居性单一国标”，而是把多个有据可依的理论和标准映射为可计算、可解释、可干预的城市状态变量。

## 2. 与耕地适宜性分析的对应关系

在耕地空间布局优化中，深度强化学习的业务价值不是单纯移动图斑，而是在耕地适宜性评价、耕地保护、坡度约束、连片化和百亩方等理论与业务目标支撑下，识别应调整地块并证明优化结果确实更合理。

UWM 城市宜居性分析与此同构：

| 耕地空间布局优化 | UWM 城市宜居性分析 |
|---|---|
| 耕地适宜性评价体系 | 城市宜居性/人居环境适宜性体系 |
| 平均坡度下降 | 热风险、空气污染暴露下降 |
| 连片度上升 | 服务、绿地、慢行和公共设施可达性改善 |
| 百亩方增加 | 形成连续、均衡、可服务的高宜居生活单元 |
| 识别应调整地块 | 识别应治理的街道、网格、街区及其适合干预动作 |
| 深度强化学习优化耕地格局 | UWM / model-based planning 优化城市干预序列 |

所以，UWM 的业务价值不是“给城市打一个宜居分数”，而是：

```text
在城市宜居性理论约束下，
识别低宜居空间单元，
解释低宜居形成机制，
推荐可实施的城市干预动作，
并证明干预后热风险、污染暴露、服务可达性、公平性和综合宜居性朝目标方向改善。
```

## 3. 学术理论依据

### 3.1 城市环境质量与人类福祉

Pacione 的城市环境质量与人类福祉研究将城市生活质量放在人文地理和环境质量框架中讨论，强调城市环境质量不仅是物理环境问题，也与居民福利、社会差异和空间分布有关。这为 UWM 把宜居性视为“环境-社会-空间复合状态”提供了基础。

可映射到 UWM 的指标包括：

```text
livability
heat_risk
air_pollution_exposure
service_accessibility
equity
```

### 3.2 城市宜居性与健康社会决定因素

Badland 等关于 urban liveability 的研究明确把宜居性指标与健康社会决定因素联系起来。该方向说明，宜居性不只是景观美观或地产价值，而是居民能否获得健康生活条件、服务机会、出行便利和社会参与机会。

这支持 UWM 将公共服务可达性、交通可达性、绿地开放空间和空间公平纳入宜居性评价，而不是只做静态土地利用或设施数量统计。

### 3.3 城市规划与人口健康

Giles-Corti 等在 The Lancet 中讨论城市规划与人口健康，将土地利用、交通、密度、公共空间、步行环境、空气污染、身体活动和健康结果联系起来。该理论基础支撑 UWM 的关键判断：城市空间干预可以通过改变环境暴露、出行行为和服务可达性影响健康与宜居性。

对应到 UWM，城市干预动作不应是抽象数学操作，而应是可解释规划动作：

```text
increase_green_infrastructure
traffic_emission_control
add_community_service
cool_roof / building_cooling_retrofit
```

### 3.4 城市绿地、公共健康与环境正义

Wolch 等关于城市绿地、公共健康和环境正义的研究说明，绿地建设既可能改善健康和环境，也可能带来空间不公平或绿色绅士化问题。因此，UWM 不能只优化全市平均宜居性，还必须检查低宜居区域、脆弱人群和高暴露群体是否真正受益。

这对应 UWM 中的 `equity` 指标和 evidence-gated planner 约束。

### 3.5 15 分钟城市与 15 分钟步行生活圈

Moreno 等提出的 15 分钟城市强调居民应在较短时间内获得日常生活所需服务与活动机会。Weng 等面向中国城市的 15 分钟步行邻里研究进一步说明，15 分钟可达性不仅是设施覆盖问题，还涉及社会不平等和健康社区建设。

这为 UWM 的 `service_accessibility`、生活圈缺口识别和公共服务补点动作提供了直接理论支撑。

### 3.6 健康城市与可持续城市

WHO Healthy Cities 和 UN SDG 11 提供了更宏观的政策理论背景：城市应更健康、安全、韧性、包容和可持续。UWM 可以把这类宏观目标落到 GIS 可计算指标上，但不能把宏观倡议直接等同于已验证的局地政策效果。

## 4. 标准、规范和技术文件依据

### 4.1 已直接核验的国家标准

`GB 3095-2026 环境空气质量标准` 是 UWM 空气污染暴露分析最直接的国家标准依据。全国标准信息公共服务平台查询结果显示，该标准为强制性国家标准，发布日期为 2026-02-27，实施日期为 2026-03-01，当前状态为现行。

它可支撑 UWM 中以下指标和输出：

```text
air_pollution_exposure
traffic_emission_control
pollution_exposure_delta
```

需要注意的是，空气质量标准可以支撑污染暴露阈值和评价口径，但不能单独定义完整城市宜居性。

### 4.2 工程建设标准与城市规划标准

以下标准是城市宜居性分析的重要规划依据，但工程建设类标准通常需要通过住房和城乡建设主管部门、正式标准出版渠道或项目采购文本复核具体条款：

| 标准号 | 名称 | 对 UWM 的支撑 |
|---|---|---|
| GB 50180-2018 | 城市居住区规划设计标准 | 居住区、生活服务设施、公共服务配套、居住环境和服务半径相关依据 |
| GB/T 51346-2019 | 城市绿地规划标准 | 绿地系统、公园绿地、开放空间和生态空间配置依据 |
| GB/T 51255-2017 | 绿色生态城区评价标准 | 绿色生态城区、人居环境、资源环境和可持续评价依据 |

这些标准适合支撑 UWM 的规划可实施性约束和服务/绿地类指标，但不宜被写成“城市宜居性唯一评价标准”。

### 4.3 社区生活圈与城市体检类技术文件

社区生活圈规划、15 分钟生活圈和城市体检评估类文件，是 UWM 做服务可达性、生活便利性、短板识别和规划干预评估的重要依据。它们可支撑：

```text
service_accessibility
equity
livability_gap_detection
add_community_service
before_after_livability_assessment
```

核验边界：此前材料中提到的 `TD/T 1062-2021` 和 `TD/T 1063-2021`，本次在全国标准信息公共服务平台行业标准备案系统中按标准号、题名关键词和 `TD` 土地管理分类检索，未核到对应记录。因此，本文不将这两个编号作为“已核验标准依据”写死。后续如果论文或申报材料需要正式引用，应以自然资源部正式发布文件、标准出版文本或项目可采购标准文本为准。

## 5. UWM 指标与理论/标准依据映射

| UWM 指标 | 业务含义 | 学术理论依据 | 标准/技术文件依据 | 结果证据 |
|---|---|---|---|---|
| `heat_risk` | 热暴露、城市热环境压力 | 环境健康、建成环境与健康、绿地降温 | 绿地规划、绿色生态城区、气象/遥感数据规范 | `heat_risk_delta < 0` |
| `air_pollution_exposure` | PM2.5、NO2、O3 等污染暴露 | 环境暴露与健康风险、交通污染健康效应 | `GB 3095-2026 环境空气质量标准` | `air_pollution_exposure_delta < 0` |
| `service_accessibility` | 医疗、教育、商业、公园、公交等服务可达性 | 可达性理论、时间地理学、15 分钟城市 | 居住区规划、社区生活圈、城市体检 | `service_accessibility_delta > 0` |
| `equity` | 低宜居区域、脆弱人群和高暴露群体是否受益 | 空间公平、环境正义、健康社会决定因素 | 城市体检、公共服务均衡、生活圈评估 | `equity_delta > 0` |
| `livability` | 综合宜居性状态 | 人居环境质量、健康城市、可持续城市 | 多标准综合支撑 | `livability_delta > 0` |

## 6. 最终结果应该是什么

UWM 的最终结果不应只是“城市宜居性排名图”，而应是证据门控的城市干预方案包。

### 6.1 低宜居区域识别

识别哪些街道、网格、街区或社区处于低宜居状态，并说明低宜居由哪些因素造成：

```text
热风险高
污染暴露高
公共服务不足
绿地或开放空间不足
脆弱人口集中
多因素叠加形成低宜居陷阱
```

### 6.2 机制解释

每个低宜居区域应给出主要机制。例如：

```text
该区域低宜居主要由热暴露和绿地不足导致；
该区域主要由空气污染暴露和道路活动压力导致；
该区域主要由公共服务可达性不足导致；
该区域平均宜居性不低，但脆弱人群暴露较高，存在公平性问题。
```

### 6.3 干预适宜性图

输出哪些空间单元适合采取哪类干预：

```text
适合增绿的单元
适合交通减排的单元
适合公共服务补点的单元
适合建筑降温改造的单元
不建议干预或证据不足的单元
```

### 6.4 多步优化方案

UWM 应输出 action sequence，而不只是单步建议：

```text
第 1 步：在高热风险且脆弱人口集中的街道增加绿地基础设施；
第 2 步：在服务缺口明显的相邻街道补充社区公共服务；
第 3 步：在污染暴露高的道路走廊实施交通减排。
```

### 6.5 前后对比指标

优化结果必须能证明干预后关键指标朝业务目标方向改善：

```text
heat_risk_delta < 0
air_pollution_exposure_delta < 0
service_accessibility_delta > 0
equity_delta > 0
livability_delta > 0
```

这与耕地优化中的“坡度下降、连片度上升、百亩方增加”是同一类证据逻辑。

### 6.6 证据等级和边界

最终报告应标注证据等级：

```text
真实观测支持
公开代理数据支持
simulator replay 支持
exploratory 情景推演
数据不足，不能用于政策主张
```

当前 `gisdataagent` 中 UWM v0 可以合理声称具备 action-conditioned rollout、evidence-gated planner、simulator replay 和 proxy 场景下的规划推演能力；但不能声称已经在真实政策 outcome 上证明优于传统城市规划方法。

## 7. 可直接写进论文/报告的表述

UWM 城市宜居性分析以健康城市、人居环境质量、环境健康暴露、公共服务可达性、15 分钟生活圈和空间公平理论为基础，并参考环境空气质量、居住区规划、城市绿地规划、绿色生态城区评价、社区生活圈和城市体检评估等标准或技术文件，构建热风险、空气污染暴露、服务可达性、空间公平和综合宜居性等指标体系。在此基础上，UWM 将城市表达为由观测、状态、干预、转移、结果和证据门控共同构成的动态系统，不仅识别低宜居区域，还进一步解释低宜居机制、推荐可实施干预动作，并通过干预前后指标变化评估方案是否真正降低环境风险、提升服务可达性和改善空间公平。

## 8. 参考来源

### 学术论文

1. Pacione, M. Urban environmental quality and human wellbeing: a social geographical perspective. Landscape and Urban Planning, 65, 19-30 (2003). DOI: https://doi.org/10.1016/S0169-2046(02)00234-7
2. Badland, H. et al. Urban liveability: Emerging lessons from Australia for exploring the potential for indicators to measure the social determinants of health. Social Science & Medicine, 111, 64-73 (2014). DOI: https://doi.org/10.1016/j.socscimed.2014.04.003
3. Giles-Corti, B. et al. City planning and population health: a global challenge. The Lancet, 388, 2912-2924 (2016). DOI: https://doi.org/10.1016/S0140-6736(16)30066-6
4. Wolch, J. R., Byrne, J. & Newell, J. P. Urban green space, public health, and environmental justice: The challenge of making cities just green enough. Landscape and Urban Planning, 125, 234-244 (2014). DOI: https://doi.org/10.1016/j.landurbplan.2014.01.017
5. Moreno, C. et al. Introducing the 15-Minute City: Sustainability, Resilience and Place Identity in Future Post-Pandemic Cities. Smart Cities, 4, 93-111 (2021). DOI: https://doi.org/10.3390/smartcities4010006
6. Weng, M. et al. The 15-minute walkable neighborhoods: Measurement, social inequalities and implications for building healthy communities in urban China. Journal of Transport & Health, 13, 259-273 (2019). DOI: https://doi.org/10.1016/j.jth.2019.05.005

### 政策与标准渠道

1. WHO European Healthy Cities Network: https://www.who.int/europe/groups/who-european-healthy-cities-network
2. United Nations SDG 11: https://sdgs.un.org/goals/goal11
3. 全国标准信息公共服务平台 `GB 3095-2026` 查询入口: https://std.samr.gov.cn/gb/search/gbQueryPage?searchText=GB%203095-2026
4. 全国标准信息公共服务平台行业标准入口: https://std.samr.gov.cn/hb/
5. 行业标准备案信息平台: https://hbba.sacinfo.org.cn/stdList
6. 住房和城乡建设部标准发布/工程建设标准核验渠道: https://www.mohurd.gov.cn/

## 9. 核验说明

本文件中的 DOI 元数据已通过 Crossref / DOI 查询核对。`GB 3095-2026` 已通过全国标准信息公共服务平台查询核对。工程建设标准和生活圈/城市体检类文件在论文正式引用前，仍应以住房和城乡建设部、自然资源部、正式标准出版文本或项目采购标准文本为准核验具体条款、实施状态和引用格式。
