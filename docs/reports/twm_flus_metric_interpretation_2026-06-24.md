# TWM vs GeoSOS-FLUS 指标解释

Date: 2026-06-24

本文解释 TWM 与 GeoSOS-FLUS 对比实验中常见指标的含义，以及数值高低分别说明什么问题。核心原则是：这些指标回答的问题不同，不能只看一个指标下结论。

## 指标分类

这些指标大致分成四类：

1. 地图分类质量：OA、Macro-F1。
2. 变化发现质量：Change FoM、Change F1、hit、false alarm、miss。
3. 需求/数量质量：oracle demand error、target-vs-oracle demand error。
4. 统计可信度：delta、wins/losses、sign-test p-value。

## OA: Overall Accuracy

OA 是总体精度：

```text
OA = 预测正确的像元数 / 所有有效像元数
```

数值越高，说明最终地图整体越像真实地图。

但土地覆盖模拟里“不变像元”通常占绝大多数，所以一个模型只要很保守、少预测变化，OA 也可能很高。因此：

- OA 高：最终地图整体稳定、保守、像真实分类图。
- OA 低：整体像元分类错误更多。
- OA 高不等于变化模拟好。

当前结果：

```text
FLUS OA: 0.918396
TWM pair guard OA: 0.895258
```

这说明 FLUS 作为“最终土地覆盖图产品”仍然更保守、更稳。

## Macro-F1

Macro-F1 是对每个类别分别计算 F1，再取平均。它不像 OA 那样让大类主导结果，小类也有同等权重。

数值越高，说明各类土地覆盖都比较均衡地预测得好。

Macro-F1 适合判断：

- 草地、林地、水体、建设用地等类别是否都还不错。
- 小类别有没有被模型忽略。
- 最终地图是否适合作为分类产品。

当前结果：

```text
FLUS macro-F1: 0.505526
TWM pair guard macro-F1: 0.467125
```

这说明 FLUS 在类别均衡分类上仍然更强。TWM 还不能说全面替代 FLUS 做最终分类图。

## Change F1

Change F1 不关心变成哪个类别，只关心一个像元是否发生变化。

它看的是二分类问题：

```text
变化 / 不变化
```

它同时考虑：

- precision：预测变化的地方有多少是真的变化。
- recall：真实变化的地方有多少被预测出来。

数值越高，说明模型更擅长找到发生变化的区域。

当前结果：

```text
FLUS change F1: 0.254339
TWM pair guard change F1: 0.322401
```

这说明 TWM 在“发现变化”上明显优于 FLUS。

## Change FoM

Change FoM 是土地变化模拟里很重要的指标：

```text
Change FoM = change hit / (change hit + false alarm + miss)
```

其中：

- hit：真实变化，模型也预测为变化。
- false alarm：模型预测变化，但真实没变。
- miss：真实变化，但模型没预测出来。

Change FoM 比 Change F1 更严格，专门看变化区域的命中质量。数值越高，说明变化模拟越好。

当前关键结果：

```text
FLUS Change FoM: 0.150955
TWM pair guard Change FoM: 0.193984
Delta: +0.043028
```

这说明 TWM 在变化模拟和变化发现上已经显著超过 FLUS。

## False Alarm 和 Miss

false alarm 和 miss 是理解模型行为的关键：

```text
false alarm = 预测变化但实际没变
miss = 实际变化但没预测出来
```

如果 false alarm 高：

- 模型太激进。
- 会报出很多不存在的变化。
- 适合探索，但不适合直接当最终图。

如果 miss 高：

- 模型太保守。
- 漏掉真实变化。
- 类似当前 FLUS 的主要问题。

当前 TWM 的特征是：

- hit 多。
- miss 少。
- false alarm 也多。

当前 FLUS 的特征是：

- false alarm 少。
- miss 很多。
- 更保守。

所以两者不是简单谁“更准”，而是偏好不同。

## Mean Delta 和 Micro Delta

Mean delta 是逐 case 平均：

```text
每个区域/年份权重一样
```

Micro delta 是像元加权：

```text
所有像元放在一起算，大区域和变化多的区域权重大
```

如果：

```text
mean delta > 0
micro delta > 0
```

说明模型不但总体像元层面更好，而且逐区域平均也更好。

pair guard 在 2023 上的结果是：

```text
2023 mean delta: +0.001053
2023 micro delta: +0.020563
```

这比之前好，因为之前 2023 是：

```text
mean delta: -0.000843
micro delta: +0.019780
```

也就是说，之前 TWM 只是像元总量上赢，逐区域平均还没赢；现在 pair guard 把 2023 的逐区域平均也拉正了。

## Wins/Losses

例如：

```text
69/31
```

意思是 100 个 paired cases 里：

- TWM 有 69 个 case 的 Change FoM 高于 FLUS。
- TWM 有 31 个 case 的 Change FoM 低于 FLUS。

这个指标很重要，因为它避免“少数大区域把平均值拉高”。

当前：

```text
TWM pair guard vs FLUS: 69/31
```

这说明不是偶然靠几个大 case 赢，而是多数 case 都赢。

## Sign-Test P-Value

sign-test p-value 是统计显著性指标。

当前：

```text
p = 0.000183
```

意思是：如果 TWM 和 FLUS 实际没有优劣差异，却观察到 69/31 这种胜负比例的概率非常低。

通常：

- p < 0.05：可以认为差异有统计显著性。
- p < 0.01：证据更强。
- p 很小：说明优势不是随机波动造成的可能性更低。

但 p-value 不表示提升幅度大小，它只表示这个胜负趋势是否可靠。

## Oracle Demand Error

Oracle demand error 是类别总量误差，不看空间位置。

可以理解为：

```text
预测出来的各类土地总面积 vs 真实各类土地总面积
```

误差越低，说明各类土地的数量更接近真实。

当前：

```text
FLUS realized oracle demand error: 226042
TWM persistence demand error: 198886
```

这说明 TWM 当前的 persistence demand 在类别数量上比 FLUS 输出更接近真实。

但数量对了，不代表位置对了，所以它不能替代 Change FoM、OA、Macro-F1。

## Transition FoM

Transition FoM 是更严格的变化机制指标。

Change FoM 只问：

```text
这个像元变没变？
```

Transition FoM 问：

```text
它是不是从正确的 source class 变到了正确的 target class？
```

例如：

```text
trees -> built
crops -> water
grass -> crops
```

这比普通变化检测更难。

pair guard 的 transition FoM：

```text
0.127849
```

高于之前 strict-overprediction frontier 的：

```text
0.107108
```

说明 pair false-alarm guard 不只是提高了“变没变”的判断，也改善了具体转移机制的空间分配。

## 如何综合理解当前结果

如果目标是最终分类图：

- 重点看 OA、Macro-F1。
- FLUS 仍然更强。
- TWM 还不能全面替代 FLUS。

如果目标是变化发现、变化热点、情景模拟、机制分析：

- 重点看 Change FoM、Change F1、Transition FoM、wins/losses。
- TWM pair guard 现在明显更强。
- 2023 缺口也已经被关闭。

## 当前科学结论

TWM 已经在变化发现和变化模拟上显著优于 GeoSOS-FLUS，但在保守最终地图分类质量上仍弱于 FLUS。
