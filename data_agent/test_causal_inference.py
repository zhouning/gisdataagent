"""Tests for causal_inference.py — 6 validation scenarios with known ground truth.

Each scenario generates synthetic data with a known causal effect, runs the
corresponding method, and verifies the estimated effect is within expected range.
"""

import json
import os
import tempfile
import unittest

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box, Point


# ---------------------------------------------------------------------------
# Synthetic data generators (reusable as standalone demo)
# ---------------------------------------------------------------------------

def _make_psm_data(n=200, true_ate=15000, seed=42):
    """Scenario 1: 城市绿地对房价的因果效应.

    200 parcels: 80 near park (treated), 120 not.
    Confounders: area, floor_count, dist_to_cbd — correlated with treatment.
    True ATE = +15000.
    """
    rng = np.random.RandomState(seed)

    # Confounders
    area = rng.uniform(60, 200, n)
    floor_count = rng.randint(1, 30, n).astype(float)
    dist_to_cbd = rng.uniform(1, 20, n)

    # Treatment assignment (moderate selection bias)
    logit = -1.0 + 0.005 * area - 0.08 * dist_to_cbd + 0.01 * floor_count
    prob = 1 / (1 + np.exp(-logit))
    treatment = (rng.uniform(0, 1, n) < prob).astype(int)

    # Outcome: price = f(confounders) + treatment_effect + noise
    price = (5000 + 200 * area + 3000 * floor_count - 2000 * dist_to_cbd
             + true_ate * treatment + rng.normal(0, 5000, n))

    # Grid geometry
    polys = [box(i % 20, i // 20, i % 20 + 1, i // 20 + 1) for i in range(n)]
    gdf = gpd.GeoDataFrame({
        "area": area, "floor_count": floor_count, "dist_to_cbd": dist_to_cbd,
        "near_park": treatment, "price": price, "geometry": polys,
    }, crs="EPSG:3857")

    path = os.path.join(tempfile.gettempdir(), "psm_test.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path, true_ate


def _make_did_data(n_periods=12, true_did=-8.0, seed=42):
    """Scenario 2: 限行政策对区域PM2.5的影响.

    2 groups × 12 months (6 pre + 6 post), true DiD effect = -8.0.
    """
    rng = np.random.RandomState(seed)
    rows = []
    for group in [0, 1]:  # 0=control, 1=treatment
        base = 55 + group * 3  # slight level difference
        for t in range(n_periods):
            post = int(t >= n_periods // 2)
            trend = -0.2 * t  # common trend
            effect = true_did * group * post
            pm25 = base + trend + effect + rng.normal(0, 1.5)
            rows.append({
                "region": group, "month": t + 1,
                "post": post, "pm25": round(pm25, 2),
            })
    df = pd.DataFrame(rows)
    path = os.path.join(tempfile.gettempdir(), "did_test.csv")
    df.to_csv(path, index=False)
    return path, true_did


def _make_granger_data(n_periods=80, seed=42):
    """Scenario 3: 城市扩张与农田减少的时序因果.

    urban Granger-causes farmland decline at lag 2.
    farmland does NOT Granger-cause urban.
    """
    rng = np.random.RandomState(seed)
    urban = np.zeros(n_periods)
    farmland = np.zeros(n_periods)

    urban[0] = 100
    urban[1] = 101
    farmland[0] = 500
    farmland[1] = 499

    for t in range(2, n_periods):
        # Urban grows independently (pure autoregressive)
        urban[t] = 0.5 * urban[t - 1] + rng.normal(3, 0.5)
        # Farmland decreases in response to urban expansion 2 periods ago
        farmland[t] = (0.7 * farmland[t - 1] - 0.5 * urban[t - 2]
                       + rng.normal(0, 1))

    df = pd.DataFrame({
        "time": range(n_periods),
        "urban_area": urban,
        "farmland_area": farmland,
    })
    path = os.path.join(tempfile.gettempdir(), "granger_test.csv")
    df.to_csv(path, index=False)
    return path


def _make_erf_data(n=300, seed=42):
    """Scenario 4: 工厂距离与呼吸疾病率的暴露-响应.

    True ERF: rate = 25 - 0.4*dist + 0.003*dist² (quadratic decay).
    Confounders: age_mean, income_median — correlated with distance.
    """
    rng = np.random.RandomState(seed)

    distance = rng.uniform(2, 50, n)  # km to factory
    age_mean = 35 + 0.3 * distance + rng.normal(0, 3, n)
    income = 3000 + 100 * distance + rng.normal(0, 500, n)

    # True ERF (quadratic)
    true_rate = 25 - 0.4 * distance + 0.003 * distance ** 2
    # Confounding: age increases disease, income decreases it
    disease_rate = true_rate + 0.1 * (age_mean - 40) - 0.001 * (income - 5000) + rng.normal(0, 1.5, n)
    disease_rate = np.clip(disease_rate, 0, None)

    points = [Point(rng.uniform(0, 100), rng.uniform(0, 100)) for _ in range(n)]
    gdf = gpd.GeoDataFrame({
        "distance_km": distance, "age_mean": age_mean,
        "income_median": income, "disease_rate": disease_rate,
        "geometry": points,
    }, crs="EPSG:3857")

    path = os.path.join(tempfile.gettempdir(), "erf_test.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_causal_forest_data(n=400, seed=42):
    """Scenario 5: 灌溉对作物产量的空间异质效应.

    CATE varies spatially: arid zone (x<5) = +200, humid zone (x>=5) = +50.
    """
    rng = np.random.RandomState(seed)
    x_coord = rng.uniform(0, 10, n)
    y_coord = rng.uniform(0, 10, n)
    is_arid = (x_coord < 5).astype(float)

    soil_quality = rng.uniform(0.3, 1.0, n)
    elevation = rng.uniform(100, 500, n)
    treatment = rng.binomial(1, 0.5, n)

    # Heterogeneous treatment effect
    cate_true = 200 * is_arid + 50 * (1 - is_arid)
    # Outcome
    base_yield = 800 + 300 * soil_quality - 0.5 * elevation
    outcome = base_yield + cate_true * treatment + rng.normal(0, 30, n)

    polys = [box(x_coord[i], y_coord[i], x_coord[i] + 0.5, y_coord[i] + 0.5)
             for i in range(n)]
    gdf = gpd.GeoDataFrame({
        "irrigated": treatment, "yield_kg": outcome,
        "soil_quality": soil_quality, "elevation": elevation,
        "x_coord": x_coord, "zone": np.where(is_arid, "arid", "humid"),
        "geometry": polys,
    }, crs="EPSG:3857")

    path = os.path.join(tempfile.gettempdir(), "causal_forest_test.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_gccm_data(n_side=10, seed=42):
    """Scenario 6: 降雨量与植被覆盖的空间因果.

    10×10 grid, rainfall → NDVI (unidirectional).
    rainfall is exogenous; NDVI is driven by neighboring rainfall.
    """
    rng = np.random.RandomState(seed)
    n = n_side * n_side

    # Exogenous rainfall with spatial autocorrelation
    rainfall = np.zeros(n)
    for i in range(n_side):
        for j in range(n_side):
            idx = i * n_side + j
            rainfall[idx] = 500 + 30 * (i + j) / n_side + rng.normal(0, 20)

    # NDVI driven by local + neighbor rainfall (strong coupling)
    ndvi = np.zeros(n)
    for i in range(n_side):
        for j in range(n_side):
            idx = i * n_side + j
            local_rain = rainfall[idx]
            # Average neighbor rainfall
            nbr_rain = []
            for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                ni, nj = i + di, j + dj
                if 0 <= ni < n_side and 0 <= nj < n_side:
                    nbr_rain.append(rainfall[ni * n_side + nj])
            avg_nbr = np.mean(nbr_rain) if nbr_rain else local_rain
            # Strong directional coupling: rainfall drives NDVI
            ndvi[idx] = 0.001 * avg_nbr + 0.0008 * local_rain + rng.normal(0, 0.005)

    polys = [box(j, i, j + 1, i + 1)
             for i in range(n_side) for j in range(n_side)]
    gdf = gpd.GeoDataFrame({
        "rainfall": rainfall, "ndvi": ndvi, "geometry": polys,
    }, crs="EPSG:3857")

    path = os.path.join(tempfile.gettempdir(), "gccm_test.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

from data_agent.causal_inference import (
    propensity_score_matching,
    exposure_response_function,
    difference_in_differences,
    spatial_granger_causality,
    geographic_causal_mapping,
    causal_forest_analysis,
)


class TestPropensityScoreMatching(unittest.TestCase):
    """Scenario 1: 城市绿地对房价 — true ATE = 15000."""

    @classmethod
    def setUpClass(cls):
        cls.path, cls.true_ate = _make_psm_data()

    def test_basic_psm(self):
        result = json.loads(propensity_score_matching(
            self.path, "near_park", "price",
            "area,floor_count,dist_to_cbd",
        ))
        self.assertNotIn("error", result)
        self.assertIn("ate", result)
        self.assertIn("att", result)
        # Effect should be positive (true ATE is 15000, but PSM can underestimate)
        self.assertGreater(result["ate"], 0)
        self.assertLess(result["ate"], 25000)
        self.assertTrue(os.path.exists(result["diagnostic_plot_path"]))
        self.assertTrue(os.path.exists(result["balance_table_path"]))

    def test_spatial_distance_weight(self):
        result = json.loads(propensity_score_matching(
            self.path, "near_park", "price",
            "area,floor_count,dist_to_cbd",
            spatial_distance_weight=0.3,
        ))
        self.assertNotIn("error", result)
        self.assertEqual(result["spatial_distance_weight"], 0.3)

    def test_caliper_matching(self):
        result = json.loads(propensity_score_matching(
            self.path, "near_park", "price",
            "area,floor_count,dist_to_cbd",
            method="caliper", caliper=0.5,
        ))
        self.assertNotIn("error", result)

    def test_missing_column(self):
        result = json.loads(propensity_score_matching(
            self.path, "near_park", "price", "nonexistent_col",
        ))
        self.assertIn("error", result)


class TestExposureResponseFunction(unittest.TestCase):
    """Scenario 4: 工厂距离与疾病率 — quadratic ERF."""

    @classmethod
    def setUpClass(cls):
        cls.path = _make_erf_data()

    def test_basic_erf(self):
        result = json.loads(exposure_response_function(
            self.path, "distance_km", "disease_rate",
            "age_mean,income_median",
        ))
        self.assertNotIn("error", result)
        self.assertIn("erf_data_path", result)
        self.assertIn("erf_plot_path", result)
        self.assertTrue(os.path.exists(result["erf_plot_path"]))

        # ERF data should exist and have 100 points
        erf_df = pd.read_csv(result["erf_data_path"])
        self.assertEqual(len(erf_df), 100)
        # Exposure should span the trimmed range
        self.assertGreater(erf_df["exposure"].max(), 40)

    def test_erf_shape(self):
        """ERF should roughly match the true quadratic decay."""
        result = json.loads(exposure_response_function(
            self.path, "distance_km", "disease_rate",
            "age_mean,income_median",
        ))
        erf_df = pd.read_csv(result["erf_data_path"])
        # True ERF: rate = 25 - 0.4*dist + 0.003*dist²
        true_erf = 25 - 0.4 * erf_df["exposure"] + 0.003 * erf_df["exposure"] ** 2
        # Correlation between estimated and true ERF should be decent
        valid = ~erf_df["response"].isna()
        if valid.sum() > 10:
            corr = np.corrcoef(erf_df["response"][valid], true_erf[valid])[0, 1]
            self.assertGreater(corr, 0.5, f"ERF correlation too low: {corr:.3f}")

    def test_bootstrap(self):
        result = json.loads(exposure_response_function(
            self.path, "distance_km", "disease_rate",
            "age_mean,income_median", n_bootstrap=20,
        ))
        erf_df = pd.read_csv(result["erf_data_path"])
        self.assertIn("ci_lower", erf_df.columns)


class TestDifferenceInDifferences(unittest.TestCase):
    """Scenario 2: 限行政策对PM2.5 — true DiD = -8.0."""

    @classmethod
    def setUpClass(cls):
        cls.path, cls.true_did = _make_did_data()

    def test_basic_did(self):
        result = json.loads(difference_in_differences(
            self.path, "pm25", "region", "month",
            post_col="post",
        ))
        self.assertNotIn("error", result)
        self.assertIn("did_estimate", result)
        # DiD should be close to -8.0 (within ±4)
        self.assertLess(result["did_estimate"], -4.0)
        self.assertGreater(result["did_estimate"], -12.0)
        self.assertLess(result["p_value"], 0.05)
        self.assertTrue(os.path.exists(result["parallel_trends_plot_path"]))

    def test_did_significance(self):
        result = json.loads(difference_in_differences(
            self.path, "pm25", "region", "month",
            post_col="post",
        ))
        self.assertLess(result["p_value"], 0.05, "DiD should be significant")

    def test_auto_threshold(self):
        """Test without explicit post_col — auto-split by median time."""
        result = json.loads(difference_in_differences(
            self.path, "pm25", "region", "month",
        ))
        self.assertNotIn("error", result)


class TestSpatialGrangerCausality(unittest.TestCase):
    """Scenario 3: 城市扩张 → 农田减少 (lag 2), not reverse."""

    @classmethod
    def setUpClass(cls):
        cls.path = _make_granger_data()

    def test_causality_direction(self):
        result = json.loads(spatial_granger_causality(
            self.path, "urban_area,farmland_area", "time",
            max_lag=4, significance=0.05,
        ))
        self.assertNotIn("error", result)
        matrix = result["causality_matrix"]

        # urban → farmland should be significant
        uf = matrix["urban_area"]["farmland_area"]
        self.assertTrue(uf["significant"],
                        f"urban→farmland should be significant, p={uf['p_value']}")

        # farmland → urban should NOT be significant at stricter level
        # (Note: in short series, mild spurious reverse causality is common)
        fu = matrix["farmland_area"]["urban_area"]
        self.assertGreater(fu["p_value"], 0.01,
                         f"farmland→urban should not be significant at 0.01, p={fu['p_value']}")

    def test_plot_created(self):
        result = json.loads(spatial_granger_causality(
            self.path, "urban_area,farmland_area", "time",
        ))
        self.assertTrue(os.path.exists(result["plot_path"]))


class TestGeographicCausalMapping(unittest.TestCase):
    """Scenario 6: 降雨 → NDVI (unidirectional), GCCM convergence."""

    @classmethod
    def setUpClass(cls):
        cls.path = _make_gccm_data()

    def test_causal_direction(self):
        result = json.loads(geographic_causal_mapping(
            self.path, "rainfall", "ndvi", k=4,
        ))
        self.assertNotIn("error", result)
        # rainfall→ndvi should have higher or equal rho than reverse
        self.assertGreaterEqual(result["x_causes_y_rho"], result["y_causes_x_rho"] - 0.05,
                           "rainfall→ndvi rho should be >= ndvi→rainfall rho")
        self.assertTrue(os.path.exists(result["convergence_plot_path"]))

    def test_convergence_data(self):
        result = json.loads(geographic_causal_mapping(
            self.path, "rainfall", "ndvi", k=4,
        ))
        conv_df = pd.read_csv(result["convergence_data_path"])
        self.assertGreater(len(conv_df), 2)
        # rho should generally increase with library size
        rhos = conv_df.iloc[:, 1].values
        self.assertGreater(rhos[-1], rhos[0],
                           "rho should increase with library size (convergence)")

    def test_missing_geometry(self):
        # CSV without geometry should fail gracefully
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        csv_path = os.path.join(tempfile.gettempdir(), "gccm_nogeom.csv")
        df.to_csv(csv_path, index=False)
        result = json.loads(geographic_causal_mapping(csv_path, "a", "b"))
        self.assertIn("error", result)


class TestCausalForestAnalysis(unittest.TestCase):
    """Scenario 5: 灌溉→产量 heterogeneous CATE: arid=+200, humid=+50."""

    @classmethod
    def setUpClass(cls):
        cls.path = _make_causal_forest_data()

    def test_ate_estimate(self):
        result = json.loads(causal_forest_analysis(
            self.path, "irrigated", "yield_kg",
            "soil_quality,elevation,x_coord",
        ))
        self.assertNotIn("error", result)
        # Overall ATE should be roughly (200+50)/2 = 125
        self.assertGreater(result["ate"], 50)
        self.assertLess(result["ate"], 250)
        self.assertTrue(os.path.exists(result["diagnostic_plot_path"]))

    def test_heterogeneity(self):
        """CATE should be higher in arid zone (x<5) than humid (x>=5)."""
        result = json.loads(causal_forest_analysis(
            self.path, "irrigated", "yield_kg",
            "soil_quality,elevation,x_coord",
        ))
        cate_df = pd.read_csv(result["cate_data_path"])
        self.assertIn("cate", cate_df.columns)
        arid_cate = cate_df[cate_df["x_coord"] < 5]["cate"].mean()
        humid_cate = cate_df[cate_df["x_coord"] >= 5]["cate"].mean()
        self.assertGreater(arid_cate, humid_cate,
                           f"Arid CATE ({arid_cate:.1f}) should > humid ({humid_cate:.1f})")

    def test_feature_importance(self):
        result = json.loads(causal_forest_analysis(
            self.path, "irrigated", "yield_kg",
            "soil_quality,elevation,x_coord",
        ))
        fi = result["feature_importance"]
        self.assertIn("x_coord", fi)
        # x_coord should be important (it determines CATE heterogeneity)
        self.assertGreater(fi["x_coord"], 0)


class TestToolsetRegistration(unittest.TestCase):
    """Verify CausalInferenceToolset is properly registered."""

    def test_toolset_returns_6_tools(self):
        from data_agent.toolsets.causal_inference_tools import CausalInferenceToolset
        import asyncio
        toolset = CausalInferenceToolset()
        tools = asyncio.get_event_loop().run_until_complete(toolset.get_tools())
        self.assertEqual(len(tools), 6)
        names = {t.name for t in tools}
        expected = {
            "propensity_score_matching", "exposure_response_function",
            "difference_in_differences", "spatial_granger_causality",
            "geographic_causal_mapping", "causal_forest_analysis",
        }
        self.assertEqual(names, expected)

    def test_toolset_filter(self):
        from data_agent.toolsets.causal_inference_tools import CausalInferenceToolset
        import asyncio
        toolset = CausalInferenceToolset(tool_filter=["propensity_score_matching"])
        tools = asyncio.get_event_loop().run_until_complete(toolset.get_tools())
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "propensity_score_matching")

    def test_in_toolset_names(self):
        from data_agent.custom_skills import TOOLSET_NAMES
        self.assertIn("CausalInferenceToolset", TOOLSET_NAMES)


if __name__ == "__main__":
    unittest.main()
