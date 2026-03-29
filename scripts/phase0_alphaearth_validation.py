"""
Phase 0: AlphaEarth 嵌入可行性验证
===================================

目标：验证 AlphaEarth 64维嵌入的年际变化信号是否足够支撑潜空间动力学学习。

验证内容：
1. 年际变化信号强度 — 相邻年份余弦相似度分布
2. 变化区域 vs 稳定区域的信号差异 — 是否可区分
3. 嵌入→土地利用类别的可解码性 — 线性分类器精度

前提：需要 GEE 账号已认证（运行 `earthengine authenticate`）

用法：
    python scripts/phase0_alphaearth_validation.py
"""

import sys
import io

# Fix Windows GBK console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import ee
import numpy as np
import os
import json
import time
from pathlib import Path

# ============================================================
# 配置
# ============================================================

# 3 个代表性验证区域（~10km × 10km 方块）
STUDY_AREAS = {
    "yangtze_delta": {
        "name": "长三角（快速城镇化）",
        "bbox": [121.2, 31.0, 121.3, 31.1],  # 上海西郊，城镇化前沿
    },
    "northeast_plain": {
        "name": "东北平原（农业稳定区）",
        "bbox": [126.5, 45.7, 126.6, 45.8],  # 哈尔滨周边农田
    },
    "yunnan_eco": {
        "name": "云南（生态变化区）",
        "bbox": [100.2, 25.0, 100.3, 25.1],  # 大理周边
    },
}

# AlphaEarth 嵌入集合
AEF_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
AEF_BANDS = [f"A{i:02d}" for i in range(64)]  # A00 ~ A63

# Sentinel-2 LULC（用作解码验证的标签）
LULC_COLLECTION = "projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS"

# 年份范围
YEARS = list(range(2017, 2024))  # 2017-2023 (7年)

# 采样密度（每个区域采样的像素数）
SAMPLE_SIZE = 500

# 输出目录
OUTPUT_DIR = Path("scripts/phase0_results")


# ============================================================
# Step 1: 初始化 GEE
# ============================================================

def init_gee():
    """初始化 Google Earth Engine。"""
    try:
        ee.Initialize()
        print("[OK] GEE initialized")
    except Exception as e:
        print(f"[FAIL] GEE init failed: {e}")
        print("Run: earthengine authenticate")
        raise


# ============================================================
# Step 2: 提取嵌入数据
# ============================================================

def get_aef_image(year: int, bbox: list) -> ee.Image:
    """获取指定年份和区域的 AlphaEarth 嵌入影像。"""
    region = ee.Geometry.Rectangle(bbox)
    img = (
        ee.ImageCollection(AEF_COLLECTION)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .filterBounds(region)
        .select(AEF_BANDS)
        .mosaic()  # 可能跨多个 UTM 瓦片
        .clip(region)
    )
    return img


def sample_embeddings(image: ee.Image, bbox: list, n_points: int = SAMPLE_SIZE) -> dict:
    """从影像中随机采样嵌入向量。返回 {band: [values...]}。"""
    region = ee.Geometry.Rectangle(bbox)
    samples = image.sample(
        region=region,
        scale=10,
        numPixels=n_points,
        seed=42,
        geometries=True,
    )
    # 提取为字典
    result = samples.getInfo()
    return result


def extract_embeddings_for_area(area_id: str, area_config: dict) -> dict:
    """提取一个区域所有年份的嵌入。"""
    bbox = area_config["bbox"]
    area_name = area_config["name"]
    print(f"\n{'='*60}")
    print(f"  区域: {area_name} ({area_id})")
    print(f"  范围: {bbox}")
    print(f"{'='*60}")

    results = {}
    for year in YEARS:
        print(f"  提取 {year} 年嵌入...", end=" ", flush=True)
        t0 = time.time()
        try:
            img = get_aef_image(year, bbox)
            samples = sample_embeddings(img, bbox)
            features = samples.get("features", [])
            n = len(features)

            if n == 0:
                print(f"[WARN] no data")
                continue

            # 转换为 numpy 数组 [n_samples, 64]
            vectors = np.array([
                [f["properties"][b] for b in AEF_BANDS]
                for f in features
                if all(b in f["properties"] for b in AEF_BANDS)
            ])

            results[year] = {
                "vectors": vectors,
                "coords": [
                    f["geometry"]["coordinates"]
                    for f in features
                    if f.get("geometry")
                ],
            }
            elapsed = time.time() - t0
            print(f"✅ {vectors.shape[0]} 样本, {vectors.shape[1]}维, {elapsed:.1f}s")

        except Exception as e:
            print(f"❌ 错误: {e}")
            continue

    return results


# ============================================================
# Step 3: 年际变化信号分析
# ============================================================

def analyze_interannual_change(area_results: dict, area_name: str) -> dict:
    """分析年际嵌入变化强度。"""
    print(f"\n--- 年际变化分析: {area_name} ---")

    years_available = sorted(area_results.keys())
    if len(years_available) < 2:
        print("  ⚠️ 不足 2 年数据，跳过")
        return {}

    metrics = {}
    for i in range(len(years_available) - 1):
        y1, y2 = years_available[i], years_available[i + 1]
        v1 = area_results[y1]["vectors"]
        v2 = area_results[y2]["vectors"]

        # 取两年都有的最小样本数
        n = min(len(v1), len(v2))
        v1, v2 = v1[:n], v2[:n]

        # 余弦相似度（向量已在单位球上，dot product = cosine sim）
        cos_sim = np.sum(v1 * v2, axis=1)  # [n]

        # 欧氏距离
        l2_dist = np.linalg.norm(v1 - v2, axis=1)  # [n]

        # 嵌入差的范数
        delta_norm = np.linalg.norm(v1 - v2, axis=1)

        pair_key = f"{y1}-{y2}"
        metrics[pair_key] = {
            "cos_sim_mean": float(np.mean(cos_sim)),
            "cos_sim_std": float(np.std(cos_sim)),
            "cos_sim_min": float(np.min(cos_sim)),
            "cos_sim_p05": float(np.percentile(cos_sim, 5)),
            "cos_sim_p50": float(np.percentile(cos_sim, 50)),
            "cos_sim_p95": float(np.percentile(cos_sim, 95)),
            "l2_dist_mean": float(np.mean(l2_dist)),
            "l2_dist_std": float(np.std(l2_dist)),
            "l2_dist_max": float(np.max(l2_dist)),
            "l2_dist_p95": float(np.percentile(l2_dist, 95)),
            "n_samples": n,
        }

        print(f"  {pair_key}: cos_sim={np.mean(cos_sim):.6f}±{np.std(cos_sim):.6f}"
              f"  L2={np.mean(l2_dist):.4f}±{np.std(l2_dist):.4f}"
              f"  (n={n})")

    # 长跨度对比
    if len(years_available) >= 4:
        y_first, y_last = years_available[0], years_available[-1]
        v_first = area_results[y_first]["vectors"]
        v_last = area_results[y_last]["vectors"]
        n = min(len(v_first), len(v_last))
        v_first, v_last = v_first[:n], v_last[:n]
        cos_long = np.sum(v_first * v_last, axis=1)
        l2_long = np.linalg.norm(v_first - v_last, axis=1)

        long_key = f"{y_first}-{y_last}"
        metrics[long_key] = {
            "cos_sim_mean": float(np.mean(cos_long)),
            "cos_sim_std": float(np.std(cos_long)),
            "cos_sim_min": float(np.min(cos_long)),
            "cos_sim_p05": float(np.percentile(cos_long, 5)),
            "cos_sim_p50": float(np.percentile(cos_long, 50)),
            "cos_sim_p95": float(np.percentile(cos_long, 95)),
            "l2_dist_mean": float(np.mean(l2_long)),
            "l2_dist_std": float(np.std(l2_long)),
            "l2_dist_max": float(np.max(l2_long)),
            "l2_dist_p95": float(np.percentile(l2_long, 95)),
            "n_samples": n,
        }
        print(f"  {long_key} (长跨度): cos_sim={np.mean(cos_long):.6f}±{np.std(cos_long):.6f}"
              f"  L2={np.mean(l2_long):.4f}±{np.std(l2_long):.4f}")

    return metrics


# ============================================================
# Step 4: 变化区域 vs 稳定区域对比
# ============================================================

def analyze_change_vs_stable(area_results: dict, area_name: str) -> dict:
    """比较嵌入变化幅度大的像素 vs 变化幅度小的像素。"""
    print(f"\n--- 变化/稳定区域对比: {area_name} ---")

    years_available = sorted(area_results.keys())
    if len(years_available) < 2:
        return {}

    y_first, y_last = years_available[0], years_available[-1]
    v_first = area_results[y_first]["vectors"]
    v_last = area_results[y_last]["vectors"]
    n = min(len(v_first), len(v_last))
    v_first, v_last = v_first[:n], v_last[:n]

    # 计算每个像素的变化幅度
    delta = np.linalg.norm(v_first - v_last, axis=1)

    # 分为高变化(top 20%) 和 低变化(bottom 20%)
    p20 = np.percentile(delta, 20)
    p80 = np.percentile(delta, 80)

    stable_mask = delta <= p20
    change_mask = delta >= p80

    result = {
        "total_samples": n,
        "delta_mean": float(np.mean(delta)),
        "delta_std": float(np.std(delta)),
        "delta_p20": float(p20),
        "delta_p80": float(p80),
        "delta_max": float(np.max(delta)),
        "stable_count": int(np.sum(stable_mask)),
        "change_count": int(np.sum(change_mask)),
        "stable_delta_mean": float(np.mean(delta[stable_mask])) if np.any(stable_mask) else None,
        "change_delta_mean": float(np.mean(delta[change_mask])) if np.any(change_mask) else None,
        "separation_ratio": float(np.mean(delta[change_mask]) / np.mean(delta[stable_mask]))
        if np.any(stable_mask) and np.any(change_mask) and np.mean(delta[stable_mask]) > 0
        else None,
    }

    print(f"  全部: Δ均值={np.mean(delta):.4f}, Δ标准差={np.std(delta):.4f}")
    print(f"  稳定区(bottom 20%): Δ={result['stable_delta_mean']:.4f}")
    print(f"  变化区(top 20%):    Δ={result['change_delta_mean']:.4f}")
    if result["separation_ratio"]:
        print(f"  分离度 (变化/稳定): {result['separation_ratio']:.2f}x")

    return result


# ============================================================
# Step 5: 嵌入→土地利用可解码性验证
# ============================================================

def get_lulc_labels(year: int, bbox: list, n_points: int = SAMPLE_SIZE) -> dict | None:
    """从 Esri Sentinel-2 LULC 获取土地利用标签。"""
    region = ee.Geometry.Rectangle(bbox)

    # 尝试多种可能的集合路径
    collection_paths = [
        "projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS",
        "GOOGLE/DYNAMICWORLD/V1",
    ]

    for path in collection_paths:
        try:
            collection = ee.ImageCollection(path)
            img = (
                collection
                .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
                .filterBounds(region)
                .first()
            )
            if img is None:
                continue

            # 获取波段名
            band_names = img.bandNames().getInfo()
            if not band_names:
                continue

            # 使用第一个波段（通常是分类结果）
            target_band = band_names[0]
            samples = img.select([target_band]).sample(
                region=region,
                scale=10,
                numPixels=n_points,
                seed=42,
            )
            result = samples.getInfo()
            features = result.get("features", [])

            if len(features) > 0:
                labels = [f["properties"][target_band] for f in features]
                print(f"    LULC 来源: {path}, 波段: {target_band}, {len(labels)} 样本")
                return {"labels": labels, "source": path, "band": target_band}

        except Exception:
            continue

    return None


def analyze_decodability(area_results: dict, area_config: dict, area_name: str) -> dict:
    """验证嵌入→土地利用类别的可解码性。"""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import LabelEncoder

    print(f"\n--- 解码能力验证: {area_name} ---")

    # 选取中间年份
    years_available = sorted(area_results.keys())
    test_year = years_available[len(years_available) // 2]  # 中间年份

    vectors = area_results[test_year]["vectors"]
    bbox = area_config["bbox"]

    print(f"  使用 {test_year} 年嵌入 ({vectors.shape[0]} 样本)")
    print(f"  获取 LULC 标签...", end=" ", flush=True)

    lulc_data = get_lulc_labels(test_year, bbox)
    if lulc_data is None:
        print("⚠️ 无法获取 LULC 标签，跳过解码验证")
        return {"status": "no_lulc_data"}

    labels = np.array(lulc_data["labels"])
    print(f"✅ {len(labels)} 标签")

    # 对齐样本数
    n = min(len(vectors), len(labels))
    X = vectors[:n]
    y = labels[:n]

    # 编码标签
    le = LabelEncoder()
    y_encoded = le.fit_transform(y)
    n_classes = len(le.classes_)
    print(f"  类别数: {n_classes}, 类别值: {le.classes_.tolist()}")

    if n_classes < 2:
        print("  ⚠️ 只有 1 个类别，跳过")
        return {"status": "single_class", "classes": le.classes_.tolist()}

    # 交叉验证
    clf = LogisticRegression(max_iter=1000, random_state=42)
    try:
        scores = cross_val_score(clf, X, y_encoded, cv=min(5, n_classes), scoring="accuracy")
        result = {
            "status": "ok",
            "year": test_year,
            "n_samples": n,
            "n_classes": n_classes,
            "classes": le.classes_.tolist(),
            "cv_accuracy_mean": float(np.mean(scores)),
            "cv_accuracy_std": float(np.std(scores)),
            "cv_scores": scores.tolist(),
            "lulc_source": lulc_data["source"],
        }
        print(f"  线性分类器 5-fold CV 精度: {np.mean(scores):.4f} ± {np.std(scores):.4f}")
        return result

    except Exception as e:
        print(f"  ❌ 分类失败: {e}")
        return {"status": "error", "error": str(e)}


# ============================================================
# Step 6: 综合判定
# ============================================================

def make_verdict(all_metrics: dict) -> dict:
    """根据所有分析结果给出综合判定。"""
    print(f"\n{'='*60}")
    print(f"  综合判定")
    print(f"{'='*60}")

    # 收集所有区域的关键指标
    all_cos_sims = []
    all_separations = []
    all_accuracies = []

    for area_id, data in all_metrics.items():
        # 年际变化
        for pair_key, m in data.get("interannual", {}).items():
            if "-" in pair_key and len(pair_key) <= 9:  # 相邻年份对
                all_cos_sims.append(m["cos_sim_mean"])

        # 分离度
        sep = data.get("change_vs_stable", {}).get("separation_ratio")
        if sep is not None:
            all_separations.append(sep)

        # 解码精度
        acc = data.get("decodability", {}).get("cv_accuracy_mean")
        if acc is not None:
            all_accuracies.append(acc)

    verdict = {"criteria": {}}

    # 判定 1: 年际变化信号
    if all_cos_sims:
        avg_cos = np.mean(all_cos_sims)
        verdict["criteria"]["interannual_signal"] = {
            "avg_cosine_similarity": float(avg_cos),
            "pass": avg_cos < 0.99,
            "strong": avg_cos < 0.95,
            "threshold": "< 0.99 (pass), < 0.95 (strong)",
        }
        status = "✅ 强信号" if avg_cos < 0.95 else ("✅ 通过" if avg_cos < 0.99 else "❌ 信号太弱")
        print(f"\n  1. 年际变化信号: 平均 cos_sim = {avg_cos:.6f} → {status}")

    # 判定 2: 变化/稳定可分离性
    if all_separations:
        avg_sep = np.mean(all_separations)
        verdict["criteria"]["change_separation"] = {
            "avg_separation_ratio": float(avg_sep),
            "pass": avg_sep > 2.0,
            "strong": avg_sep > 5.0,
            "threshold": "> 2x (pass), > 5x (strong)",
        }
        status = "✅ 强分离" if avg_sep > 5 else ("✅ 通过" if avg_sep > 2 else "❌ 分离不足")
        print(f"  2. 变化/稳定分离度: {avg_sep:.2f}x → {status}")

    # 判定 3: 解码能力
    if all_accuracies:
        avg_acc = np.mean(all_accuracies)
        verdict["criteria"]["decodability"] = {
            "avg_accuracy": float(avg_acc),
            "pass": avg_acc > 0.5,
            "strong": avg_acc > 0.7,
            "threshold": "> 50% (pass), > 70% (strong)",
        }
        status = "✅ 强解码" if avg_acc > 0.7 else ("✅ 通过" if avg_acc > 0.5 else "❌ 解码不足")
        print(f"  3. 嵌入→LULC 解码精度: {avg_acc:.4f} → {status}")

    # 总体判定
    criteria_results = verdict["criteria"]
    all_pass = all(c.get("pass", False) for c in criteria_results.values())
    any_strong = any(c.get("strong", False) for c in criteria_results.values())
    all_strong = all(c.get("strong", False) for c in criteria_results.values())

    if all_strong:
        verdict["overall"] = "STRONG_PASS"
        verdict["recommendation"] = "方案 D（AlphaEarth + 潜空间动力学）强烈推荐，所有指标优秀"
    elif all_pass:
        verdict["overall"] = "PASS"
        verdict["recommendation"] = "方案 D 可行，信号足以支撑动力学学习"
    elif any_strong:
        verdict["overall"] = "PARTIAL_PASS"
        verdict["recommendation"] = "部分指标通过，建议进一步实验或考虑增强方法（差分编码/注意力放大）"
    else:
        verdict["overall"] = "FAIL"
        verdict["recommendation"] = "方案 D 不可行，建议退回方案 B（Sentinel-2 LULC 像素空间训练）"

    print(f"\n  ══════════════════════════════════════")
    print(f"  总体判定: {verdict['overall']}")
    print(f"  建议: {verdict['recommendation']}")
    print(f"  ══════════════════════════════════════")

    return verdict


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("  Phase 0: AlphaEarth 嵌入可行性验证")
    print("  目标: 验证嵌入年际变化信号能否支撑动力学学习")
    print("=" * 60)

    # 初始化
    init_gee()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_metrics = {}

    for area_id, area_config in STUDY_AREAS.items():
        # 提取嵌入
        area_results = extract_embeddings_for_area(area_id, area_config)

        if not area_results:
            print(f"  ⚠️ {area_id} 无数据，跳过")
            continue

        area_name = area_config["name"]

        # 分析 1: 年际变化
        interannual = analyze_interannual_change(area_results, area_name)

        # 分析 2: 变化 vs 稳定
        change_stable = analyze_change_vs_stable(area_results, area_name)

        # 分析 3: 解码能力
        decodability = analyze_decodability(area_results, area_config, area_name)

        all_metrics[area_id] = {
            "area_name": area_name,
            "interannual": interannual,
            "change_vs_stable": change_stable,
            "decodability": decodability,
        }

    # 综合判定
    verdict = make_verdict(all_metrics)

    # 保存结果
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "study_areas": {k: v["name"] for k, v in STUDY_AREAS.items()},
            "years": YEARS,
            "sample_size": SAMPLE_SIZE,
            "aef_collection": AEF_COLLECTION,
        },
        "metrics": {},
        "verdict": verdict,
    }

    # 清理 numpy 类型（JSON 不能序列化 numpy）
    for area_id, data in all_metrics.items():
        clean_data = {
            "area_name": data["area_name"],
            "interannual": data["interannual"],
            "change_vs_stable": data["change_vs_stable"],
            "decodability": data["decodability"],
        }
        output["metrics"][area_id] = clean_data

    # numpy 类型转原生 Python
    def _convert(obj):
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_convert(v) for v in obj]
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    output_path = OUTPUT_DIR / "phase0_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(_convert(output), f, ensure_ascii=False, indent=2)
    print(f"\n📄 结果已保存: {output_path}")

    # 生成可视化报告
    try:
        generate_report(all_metrics, verdict)
    except Exception as e:
        print(f"⚠️ 可视化报告生成失败 (不影响结果): {e}")

    return verdict


def generate_report(all_metrics: dict, verdict: dict):
    """生成可视化报告 (matplotlib)。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle("Phase 0: AlphaEarth Embedding Interannual Change Analysis",
                 fontsize=14, fontweight="bold")

    colors = {"yangtze_delta": "#e74c3c", "northeast_plain": "#2ecc71", "yunnan_eco": "#3498db"}
    labels = {"yangtze_delta": "Yangtze Delta (Urban)",
              "northeast_plain": "NE Plain (Agriculture)",
              "yunnan_eco": "Yunnan (Ecological)"}

    # Plot 1: Cosine similarity over consecutive years
    ax1 = axes[0]
    for area_id, data in all_metrics.items():
        interannual = data.get("interannual", {})
        pairs = [(k, v["cos_sim_mean"]) for k, v in interannual.items()
                 if len(k) <= 9]  # 只取相邻年份
        if pairs:
            pairs.sort()
            x_labels = [p[0] for p in pairs]
            y_vals = [p[1] for p in pairs]
            ax1.plot(range(len(pairs)), y_vals, "o-",
                     color=colors.get(area_id, "gray"),
                     label=labels.get(area_id, area_id), markersize=6)
    ax1.axhline(y=0.99, color="red", linestyle="--", alpha=0.5, label="Threshold (0.99)")
    ax1.axhline(y=0.95, color="orange", linestyle="--", alpha=0.5, label="Strong (0.95)")
    ax1.set_xlabel("Year Pair")
    ax1.set_ylabel("Cosine Similarity")
    ax1.set_title("Interannual Embedding Stability")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    # Plot 2: Change vs Stable separation
    ax2 = axes[1]
    area_names = []
    stable_vals = []
    change_vals = []
    for area_id, data in all_metrics.items():
        cs = data.get("change_vs_stable", {})
        if cs.get("stable_delta_mean") and cs.get("change_delta_mean"):
            area_names.append(labels.get(area_id, area_id).split("(")[0].strip())
            stable_vals.append(cs["stable_delta_mean"])
            change_vals.append(cs["change_delta_mean"])
    if area_names:
        x = np.arange(len(area_names))
        width = 0.35
        ax2.bar(x - width / 2, stable_vals, width, label="Stable (bottom 20%)", color="#2ecc71")
        ax2.bar(x + width / 2, change_vals, width, label="Changed (top 20%)", color="#e74c3c")
        ax2.set_xticks(x)
        ax2.set_xticklabels(area_names, fontsize=9)
        ax2.set_ylabel("L2 Distance (2017→2023)")
        ax2.set_title("Changed vs Stable Pixels")
        ax2.legend()
        ax2.grid(True, alpha=0.3, axis="y")

    # Plot 3: Decodability
    ax3 = axes[2]
    dec_names = []
    dec_accs = []
    dec_stds = []
    for area_id, data in all_metrics.items():
        dec = data.get("decodability", {})
        if dec.get("cv_accuracy_mean"):
            dec_names.append(labels.get(area_id, area_id).split("(")[0].strip())
            dec_accs.append(dec["cv_accuracy_mean"])
            dec_stds.append(dec.get("cv_accuracy_std", 0))
    if dec_names:
        x = np.arange(len(dec_names))
        ax3.bar(x, dec_accs, yerr=dec_stds, color="#3498db", capsize=5)
        ax3.axhline(y=0.5, color="red", linestyle="--", alpha=0.5, label="Chance (50%)")
        ax3.axhline(y=0.7, color="orange", linestyle="--", alpha=0.5, label="Strong (70%)")
        ax3.set_xticks(x)
        ax3.set_xticklabels(dec_names, fontsize=9)
        ax3.set_ylabel("Classification Accuracy")
        ax3.set_title("Embedding → LULC Decodability")
        ax3.set_ylim(0, 1)
        ax3.legend()
        ax3.grid(True, alpha=0.3, axis="y")

    # Verdict banner
    overall = verdict.get("overall", "UNKNOWN")
    color_map = {"STRONG_PASS": "green", "PASS": "limegreen",
                 "PARTIAL_PASS": "orange", "FAIL": "red"}
    fig.text(0.5, 0.01,
             f"Verdict: {overall} — {verdict.get('recommendation', '')}",
             ha="center", fontsize=11, fontweight="bold",
             color=color_map.get(overall, "gray"),
             bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))

    plt.tight_layout(rect=[0, 0.05, 1, 0.95])
    report_path = OUTPUT_DIR / "phase0_report.png"
    plt.savefig(report_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"📊 可视化报告: {report_path}")


if __name__ == "__main__":
    main()
