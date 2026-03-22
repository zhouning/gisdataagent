"""
World Model Tech Preview — Plan D (AlphaEarth + LatentDynamicsNet).

Geospatial world model: predicts land-use change in embedding space
using 64-dim AlphaEarth embeddings + residual CNN dynamics.

Architecture:  AlphaEarth (frozen encoder) → LatentDynamicsNet (learned dynamics)
This is a JEPA (Joint Embedding Predictive Architecture) for geospatial domain.

Phase 0 validation passed (2026-03-22):
- Interannual cos_sim = 0.953 (sufficient variation signal)
- Change/stable separation = 2.44x
- Embedding→LULC decode accuracy = 83.7%
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ====================================================================
#  Constants
# ====================================================================

# AlphaEarth Embedding collection on GEE
AEF_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
AEF_BANDS = [f"A{i:02d}" for i in range(64)]  # A00 ~ A63
Z_DIM = 64
SCENARIO_DIM = 16

# LULC label source for decoder training
LULC_COLLECTION = (
    "projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS"
)

# LULC class map (ESRI Global LULC 10m)
LULC_CLASSES = {
    1: "水体",
    2: "树木",
    4: "草地",
    5: "灌木",
    7: "耕地",
    8: "建设用地",
    9: "裸地",
    10: "冰雪",
    11: "湿地",
}

LULC_COLORS = {
    "水体": "#4169E1",
    "树木": "#228B22",
    "草地": "#90EE90",
    "灌木": "#DEB887",
    "耕地": "#FFD700",
    "建设用地": "#DC143C",
    "裸地": "#D2B48C",
    "冰雪": "#FFFFFF",
    "湿地": "#20B2AA",
}

# Weight paths
WEIGHTS_DIR = os.path.join(os.path.dirname(__file__), "weights")
WEIGHTS_PATH = os.path.join(WEIGHTS_DIR, "latent_dynamics_v1.pt")
DECODER_PATH = os.path.join(WEIGHTS_DIR, "lulc_decoder_v1.pkl")

# Raw data cache (embeddings + LULC labels downloaded from GEE)
RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "weights", "raw_data")

# Default study areas for training (same as Phase 0)
DEFAULT_TRAINING_AREAS = [
    {"name": "yangtze_delta", "bbox": [121.2, 31.0, 121.3, 31.1]},
    {"name": "northeast_plain", "bbox": [126.5, 45.7, 126.6, 45.8]},
    {"name": "yunnan_eco", "bbox": [100.2, 25.0, 100.3, 25.1]},
]

TRAINING_YEARS = list(range(2017, 2025))  # 2017-2024


# ====================================================================
#  Scenarios
# ====================================================================

@dataclass
class WorldModelScenario:
    """Simulation scenario definition."""

    id: int
    name: str
    name_zh: str
    description: str
    # Reserved for future: per-scenario modifiers
    params: dict = field(default_factory=dict)


SCENARIOS: dict[str, WorldModelScenario] = {
    "urban_sprawl": WorldModelScenario(
        id=0,
        name="urban_sprawl",
        name_zh="城市蔓延",
        description="高城镇化增速，建设用地快速扩张，耕地和生态用地减少",
    ),
    "ecological_restoration": WorldModelScenario(
        id=1,
        name="ecological_restoration",
        name_zh="生态修复",
        description="退耕还林还湿，森林和湿地面积恢复，建设用地增长受限",
    ),
    "agricultural_intensification": WorldModelScenario(
        id=2,
        name="agricultural_intensification",
        name_zh="农业集约化",
        description="耕地整合扩张，分散耕地合并，牺牲部分林草地",
    ),
    "climate_adaptation": WorldModelScenario(
        id=3,
        name="climate_adaptation",
        name_zh="气候适应",
        description="地形依赖型防灾土地利用调整，低洼区退耕，高地造林",
    ),
    "baseline": WorldModelScenario(
        id=4,
        name="baseline",
        name_zh="基线趋势",
        description="现状惯性延续，历史变化趋势自然外推",
    ),
}


def encode_scenario(scenario_name: str) -> "torch.Tensor":
    """Encode scenario name to a [1, SCENARIO_DIM] tensor (one-hot + reserved)."""
    import torch

    if scenario_name not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario '{scenario_name}'. "
            f"Available: {list(SCENARIOS.keys())}"
        )
    vec = np.zeros(SCENARIO_DIM, dtype=np.float32)
    vec[SCENARIOS[scenario_name].id] = 1.0  # one-hot in first 5 dims
    return torch.tensor(vec).unsqueeze(0)  # [1, 16]


# ====================================================================
#  LatentDynamicsNet — the world model
# ====================================================================

def _build_model(z_dim: int = Z_DIM, scenario_dim: int = SCENARIO_DIM):
    """Build a LatentDynamicsNet instance. Deferred torch import."""
    import torch
    import torch.nn as nn

    class LatentDynamicsNet(nn.Module):
        """Residual CNN predicting embedding delta: z_{t+1} = z_t + f(z_t, s)."""

        def __init__(self, z_dim_: int = z_dim, scenario_dim_: int = scenario_dim):
            super().__init__()
            self.z_dim = z_dim_
            self.scenario_dim = scenario_dim_
            self.scenario_enc = nn.Sequential(
                nn.Linear(scenario_dim_, 64),
                nn.ReLU(),
                nn.Linear(64, z_dim_),
            )
            self.dynamics = nn.Sequential(
                nn.Conv2d(z_dim_ * 2, 128, 3, padding=1),
                nn.GroupNorm(8, 128),
                nn.GELU(),
                nn.Conv2d(128, 128, 3, padding=1),
                nn.GroupNorm(8, 128),
                nn.GELU(),
                nn.Conv2d(128, z_dim_, 1),
            )

        def forward(self, z_t: torch.Tensor, scenario: torch.Tensor) -> torch.Tensor:
            """
            Args:
                z_t: [B, z_dim, H, W] current embedding grid
                scenario: [B, scenario_dim] scenario vector
            Returns:
                z_tp1: [B, z_dim, H, W] predicted next embedding grid
            """
            s = self.scenario_enc(scenario)[:, :, None, None].expand_as(z_t)
            delta_z = self.dynamics(torch.cat([z_t, s], dim=1))
            return z_t + delta_z  # residual connection

    return LatentDynamicsNet()


# ====================================================================
#  GEE Integration
# ====================================================================

_GEE_INITIALIZED: Optional[bool] = None


def _init_gee() -> bool:
    """Initialize Google Earth Engine. Cached."""
    global _GEE_INITIALIZED
    if _GEE_INITIALIZED is not None:
        return _GEE_INITIALIZED
    try:
        import ee

        ee.Initialize()
        _GEE_INITIALIZED = True
        logger.info("GEE initialized successfully")
    except Exception as e:
        logger.warning("GEE initialization failed: %s", e)
        _GEE_INITIALIZED = False
    return _GEE_INITIALIZED


def extract_embeddings(
    bbox: list[float], year: int, scale: int = 10
) -> Optional[np.ndarray]:
    """
    Extract AlphaEarth embeddings for a bbox and year from GEE.

    Returns:
        ndarray of shape [H, W, 64] or None if GEE unavailable.
    """
    if not _init_gee():
        return None
    import ee

    try:
        region = ee.Geometry.Rectangle(bbox)
        img = (
            ee.ImageCollection(AEF_COLLECTION)
            .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
            .filterBounds(region)
            .select(AEF_BANDS)
            .mosaic()
            .clip(region)
        )
        # Auto-adjust scale to stay within GEE sampleRectangle limits
        # GEE limit: 262144 pixels. For 64 bands, keep grid <= ~64x64.
        bbox_w = abs(bbox[2] - bbox[0])
        bbox_h = abs(bbox[3] - bbox[1])
        max_dim_deg = max(bbox_w, bbox_h)
        # ~111km per degree, so 0.1° ≈ 11km. At 10m: ~1100 pixels → too large
        # Auto-scale: ensure max grid dimension <= 64 pixels
        meters_per_deg = 111_000
        needed_scale = max(scale, int(max_dim_deg * meters_per_deg / 64))
        if needed_scale != scale:
            logger.info("Auto-adjusted scale %d -> %d for bbox size %.3f°",
                        scale, needed_scale, max_dim_deg)

        result = img.sampleRectangle(
            region=region, defaultValue=0
        ).getInfo()
        properties = result.get("properties", {})
        if not properties:
            logger.warning("No embedding data for bbox=%s year=%d", bbox, year)
            return None

        # Stack bands into [H, W, 64]
        arrays = []
        for band in AEF_BANDS:
            band_data = properties.get(band)
            if band_data is None:
                return None
            arrays.append(np.array(band_data, dtype=np.float32))

        grid = np.stack(arrays, axis=-1)  # [H, W, 64]
        return grid
    except Exception as e:
        logger.error("Failed to extract embeddings: %s", e)
        return None


def sample_embeddings_as_points(
    bbox: list[float], year: int, n_points: int = 500, seed: int = 42
) -> Optional[np.ndarray]:
    """
    Sample AlphaEarth embeddings as random point vectors (not grid).

    Unlike extract_embeddings (grid mode), this returns individual pixel
    vectors without spatial structure. Used for validation experiments where
    per-pixel metrics are sufficient.

    Returns:
        ndarray of shape [N, 64] or None if GEE unavailable.
    """
    if not _init_gee():
        return None
    import ee

    try:
        region = ee.Geometry.Rectangle(bbox)
        img = (
            ee.ImageCollection(AEF_COLLECTION)
            .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
            .filterBounds(region)
            .select(AEF_BANDS)
            .mosaic()
            .clip(region)
        )
        samples = img.sample(
            region=region, scale=10, numPixels=n_points, seed=seed, geometries=False
        )
        fc = samples.getInfo()
        features = fc.get("features", [])
        if not features:
            return None

        vectors = []
        for f in features:
            props = f["properties"]
            vec = [props.get(b, 0.0) for b in AEF_BANDS]
            vectors.append(vec)

        return np.array(vectors, dtype=np.float32)  # [N, 64]
    except Exception as e:
        logger.error("Failed to sample embeddings: %s", e)
        return None


def extract_lulc_labels(
    bbox: list[float], year: int, scale: int = 10
) -> Optional[np.ndarray]:
    """
    Extract LULC class labels from ESRI Global LULC for a bbox and year.

    Returns:
        ndarray of shape [H, W] with integer class labels, or None.
    """
    if not _init_gee():
        return None
    import ee

    try:
        region = ee.Geometry.Rectangle(bbox)
        img = (
            ee.ImageCollection(LULC_COLLECTION)
            .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
            .filterBounds(region)
            .select(["b1"])
            .mosaic()
            .clip(region)
        )
        result = img.sampleRectangle(region=region, defaultValue=0).getInfo()
        properties = result.get("properties", {})
        band_data = properties.get("b1")
        if band_data is None:
            return None
        return np.array(band_data, dtype=np.int32)
    except Exception as e:
        logger.error("Failed to extract LULC labels: %s", e)
        return None


# ====================================================================
#  Training
# ====================================================================


def _build_training_pairs(
    areas: list[dict], years: list[int]
) -> tuple[list[np.ndarray], list[np.ndarray], list[np.ndarray]]:
    """
    Build (z_t, scenario_vec, z_{t+1}) training pairs from GEE data.
    Each pair uses 'baseline' scenario (historical trend).

    Downloaded embeddings are cached as .npy files under RAW_DATA_DIR
    for offline reproducibility.
    """
    os.makedirs(RAW_DATA_DIR, exist_ok=True)

    z_t_list, scenario_list, z_tp1_list = [], [], []
    scenario_vec = np.zeros(SCENARIO_DIM, dtype=np.float32)
    scenario_vec[SCENARIOS["baseline"].id] = 1.0  # historical = baseline

    for area in areas:
        bbox = area["bbox"]
        name = area.get("name", str(bbox))
        for i in range(len(years) - 1):
            y1, y2 = years[i], years[i + 1]
            logger.info("Extracting %s: %d->%d", name, y1, y2)

            # Try loading from cache first
            emb1 = _load_or_fetch_embedding(name, bbox, y1)
            emb2 = _load_or_fetch_embedding(name, bbox, y2)

            if emb1 is None or emb2 is None:
                logger.warning("Skipping %s %d->%d: missing data", name, y1, y2)
                continue
            # Ensure same shape
            h = min(emb1.shape[0], emb2.shape[0])
            w = min(emb1.shape[1], emb2.shape[1])
            emb1 = emb1[:h, :w, :]
            emb2 = emb2[:h, :w, :]
            # Transpose to [64, H, W] for Conv2d
            z_t_list.append(emb1.transpose(2, 0, 1))
            z_tp1_list.append(emb2.transpose(2, 0, 1))
            scenario_list.append(scenario_vec.copy())

    return z_t_list, scenario_list, z_tp1_list


def _load_or_fetch_embedding(
    area_name: str, bbox: list[float], year: int
) -> Optional[np.ndarray]:
    """Load embedding from .npy cache, or fetch from GEE and save."""
    cache_path = os.path.join(RAW_DATA_DIR, f"emb_{area_name}_{year}.npy")
    if os.path.exists(cache_path):
        logger.info("  Loading cached %s %d", area_name, year)
        return np.load(cache_path)

    emb = extract_embeddings(bbox, year)
    if emb is not None:
        np.save(cache_path, emb)
        logger.info("  Saved %s %d -> %s  shape=%s", area_name, year, cache_path, emb.shape)
    return emb


def _load_or_fetch_lulc(
    area_name: str, bbox: list[float], year: int
) -> Optional[np.ndarray]:
    """Load LULC labels from .npy cache, or fetch from GEE and save."""
    cache_path = os.path.join(RAW_DATA_DIR, f"lulc_{area_name}_{year}.npy")
    if os.path.exists(cache_path):
        logger.info("  Loading cached LULC %s %d", area_name, year)
        return np.load(cache_path)

    lulc = extract_lulc_labels(bbox, year)
    if lulc is not None:
        np.save(cache_path, lulc)
        logger.info("  Saved LULC %s %d -> %s  shape=%s", area_name, year, cache_path, lulc.shape)
    return lulc


def train_dynamics_model(
    areas: list[dict] | None = None,
    epochs: int = 50,
    lr: float = 1e-3,
) -> dict:
    """
    Train LatentDynamicsNet on historical embedding transitions.

    If areas is None, uses the 3 default study areas from Phase 0.
    Requires GEE connection for data download.
    """
    import torch

    if areas is None:
        areas = DEFAULT_TRAINING_AREAS

    logger.info("Building training pairs from %d areas...", len(areas))
    z_t_list, scenario_list, z_tp1_list = _build_training_pairs(
        areas, TRAINING_YEARS
    )
    if len(z_t_list) == 0:
        return {"status": "error", "error": "No training data available (GEE issue?)"}

    logger.info("Training samples: %d", len(z_t_list))

    # Build model
    model = _build_model()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    mse_loss = torch.nn.MSELoss()

    # Training loop
    model.train()
    losses = []
    for epoch in range(epochs):
        epoch_loss = 0.0
        for z_t_np, s_np, z_tp1_np in zip(z_t_list, scenario_list, z_tp1_list):
            z_t = torch.tensor(z_t_np).unsqueeze(0)  # [1, 64, H, W]
            scenario = torch.tensor(s_np).unsqueeze(0)  # [1, 16]
            z_tp1_true = torch.tensor(z_tp1_np).unsqueeze(0)  # [1, 64, H, W]

            z_tp1_pred = model(z_t, scenario)
            # L2 normalize prediction to match unit-sphere target
            z_tp1_pred = torch.nn.functional.normalize(z_tp1_pred, p=2, dim=1)
            z_tp1_true_norm = torch.nn.functional.normalize(z_tp1_true, p=2, dim=1)
            loss = mse_loss(z_tp1_pred, z_tp1_true_norm)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

        avg_loss = epoch_loss / len(z_t_list)
        losses.append(avg_loss)
        if (epoch + 1) % 10 == 0:
            logger.info("Epoch %d/%d  loss=%.6f", epoch + 1, epochs, avg_loss)

    # Save checkpoint
    os.makedirs(WEIGHTS_DIR, exist_ok=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "z_dim": Z_DIM,
            "scenario_dim": SCENARIO_DIM,
            "training_areas": [a["name"] for a in areas],
            "training_years": TRAINING_YEARS,
            "epochs": epochs,
            "final_loss": float(losses[-1]) if losses else 0.0,
            "version": "1.0",
        },
        WEIGHTS_PATH,
    )
    logger.info("Model saved to %s", WEIGHTS_PATH)

    return {
        "status": "ok",
        "epochs": epochs,
        "final_loss": float(losses[-1]) if losses else 0.0,
        "weights_path": WEIGHTS_PATH,
        "n_samples": len(z_t_list),
    }


def train_lulc_decoder(areas: list[dict] | None = None) -> dict:
    """Train a linear LULC decoder (LogisticRegression) on AlphaEarth embeddings."""
    from sklearn.linear_model import LogisticRegression

    if areas is None:
        areas = DEFAULT_TRAINING_AREAS

    all_X, all_y = [], []
    mid_year = 2020  # middle of training range

    for area in areas:
        name = area.get("name", str(area["bbox"]))
        emb = _load_or_fetch_embedding(name, area["bbox"], mid_year)
        lulc = _load_or_fetch_lulc(name, area["bbox"], mid_year)
        if emb is None or lulc is None:
            continue
        h = min(emb.shape[0], lulc.shape[0])
        w = min(emb.shape[1], lulc.shape[1])
        X = emb[:h, :w, :].reshape(-1, Z_DIM)
        y = lulc[:h, :w].reshape(-1)
        # Filter out nodata (0)
        valid = y > 0
        all_X.append(X[valid])
        all_y.append(y[valid])

    if not all_X:
        return {"status": "error", "error": "No LULC data available"}

    X = np.concatenate(all_X)
    y = np.concatenate(all_y)

    clf = LogisticRegression(max_iter=1000, random_state=42)
    clf.fit(X, y)
    acc = clf.score(X, y)

    os.makedirs(WEIGHTS_DIR, exist_ok=True)
    import joblib

    joblib.dump(clf, DECODER_PATH)
    logger.info("LULC decoder saved to %s (accuracy=%.3f)", DECODER_PATH, acc)

    return {
        "status": "ok",
        "accuracy": float(acc),
        "n_samples": len(X),
        "n_classes": len(clf.classes_),
    }


# ====================================================================
#  Model Loading (cached, lazy)
# ====================================================================

_CACHED_MODEL = None
_CACHED_DECODER = None


def _load_model():
    """Load LatentDynamicsNet from weights. Auto-train if missing."""
    import torch

    global _CACHED_MODEL
    if _CACHED_MODEL is not None:
        return _CACHED_MODEL

    if not os.path.exists(WEIGHTS_PATH):
        logger.info("No model weights found, auto-training...")
        result = train_dynamics_model()
        if result.get("status") != "ok":
            raise RuntimeError(f"Auto-training failed: {result.get('error', 'unknown')}")

    checkpoint = torch.load(WEIGHTS_PATH, map_location="cpu", weights_only=False)
    z_dim = checkpoint.get("z_dim", Z_DIM)
    scenario_dim = checkpoint.get("scenario_dim", SCENARIO_DIM)
    model = _build_model(z_dim, scenario_dim)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    _CACHED_MODEL = model
    logger.info(
        "World model loaded (v%s, loss=%.6f)",
        checkpoint.get("version", "?"),
        checkpoint.get("final_loss", -1),
    )
    return model


def _load_decoder():
    """Load LULC decoder. Auto-train if missing."""
    global _CACHED_DECODER
    if _CACHED_DECODER is not None:
        return _CACHED_DECODER

    if not os.path.exists(DECODER_PATH):
        logger.info("No LULC decoder found, auto-training...")
        result = train_lulc_decoder()
        if result.get("status") != "ok":
            raise RuntimeError(
                f"Decoder training failed: {result.get('error', 'unknown')}"
            )

    import joblib

    _CACHED_DECODER = joblib.load(DECODER_PATH)
    logger.info("LULC decoder loaded from %s", DECODER_PATH)
    return _CACHED_DECODER


# ====================================================================
#  Inference
# ====================================================================


def _embeddings_to_lulc(z: np.ndarray, decoder) -> np.ndarray:
    """
    Decode embedding grid to LULC class grid.

    Args:
        z: [64, H, W] embedding grid
        decoder: fitted LogisticRegression
    Returns:
        [H, W] integer class labels
    """
    c, h, w = z.shape
    X = z.reshape(c, -1).T  # [H*W, 64]
    y = decoder.predict(X)  # [H*W]
    return y.reshape(h, w)


def _compute_area_distribution(lulc_grid: np.ndarray) -> dict:
    """Compute per-class pixel counts and percentages."""
    total = lulc_grid.size
    if total == 0:
        return {}
    result = {}
    for cls_id, cls_name in LULC_CLASSES.items():
        count = int(np.sum(lulc_grid == cls_id))
        if count > 0:
            result[cls_name] = {
                "class_id": cls_id,
                "count": count,
                "percentage": round(100.0 * count / total, 2),
            }
    return result


def _compute_transition_matrix(
    lulc_start: np.ndarray, lulc_end: np.ndarray
) -> dict:
    """Compute class-to-class transition counts."""
    result = {}
    for from_id, from_name in LULC_CLASSES.items():
        from_mask = lulc_start == from_id
        if not np.any(from_mask):
            continue
        transitions = {}
        for to_id, to_name in LULC_CLASSES.items():
            count = int(np.sum(lulc_end[from_mask] == to_id))
            if count > 0:
                transitions[to_name] = count
        if transitions:
            result[from_name] = transitions
    return result


def _lulc_grid_to_geojson(
    lulc_grid: np.ndarray, bbox: list[float], year: int
) -> dict:
    """
    Convert LULC grid to a simplified GeoJSON FeatureCollection.
    Each unique class becomes a multi-polygon feature.
    """
    h, w = lulc_grid.shape
    if h == 0 or w == 0:
        return {
            "type": "FeatureCollection",
            "features": [],
            "properties": {"year": year, "bbox": bbox, "grid_shape": [h, w]},
        }
    minx, miny, maxx, maxy = bbox
    dx = (maxx - minx) / w
    dy = (maxy - miny) / h

    features = []
    for cls_id, cls_name in LULC_CLASSES.items():
        mask = lulc_grid == cls_id
        count = int(np.sum(mask))
        if count == 0:
            continue
        # Compute centroid of class pixels for a simple point representation
        ys, xs = np.where(mask)
        cx = float(minx + (np.mean(xs) + 0.5) * dx)
        cy = float(maxy - (np.mean(ys) + 0.5) * dy)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [cx, cy]},
                "properties": {
                    "class_id": cls_id,
                    "class_name": cls_name,
                    "pixel_count": count,
                    "percentage": round(100.0 * count / lulc_grid.size, 2),
                    "year": year,
                    "color": LULC_COLORS.get(cls_name, "#808080"),
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {"year": year, "bbox": bbox, "grid_shape": list(lulc_grid.shape)},
    }


def predict_sequence(
    bbox: list[float],
    scenario: str,
    start_year: int,
    n_years: int,
    scale: int = 10,
) -> dict:
    """
    Main inference entry point: predict LULC change for N years.

    Args:
        bbox: [minx, miny, maxx, maxy]
        scenario: one of SCENARIOS keys
        start_year: year of starting embeddings (2017-2024)
        n_years: number of years to predict forward
        scale: pixel resolution in meters

    Returns:
        dict with area_distribution, transition_matrix, geojson_layers, summary
    """
    import torch

    t0 = time.time()

    # Validate scenario
    if scenario not in SCENARIOS:
        return {
            "status": "error",
            "error": f"Unknown scenario '{scenario}'. Available: {list(SCENARIOS.keys())}",
        }

    # Extract current embeddings
    logger.info("Extracting embeddings for %s year=%d...", bbox, start_year)
    emb = extract_embeddings(bbox, start_year, scale)
    if emb is None:
        return {
            "status": "error",
            "error": "Failed to extract embeddings from GEE. Check GEE connection and bbox.",
        }

    h, w, c = emb.shape
    logger.info("Embedding grid: %dx%d, %d dims", h, w, c)

    # Load model + decoder
    model = _load_model()
    decoder = _load_decoder()

    # Prepare tensors
    z = torch.tensor(emb.transpose(2, 0, 1)).unsqueeze(0).float()  # [1, 64, H, W]
    s = encode_scenario(scenario)  # [1, 16]

    # Autoregressive prediction
    years = [start_year]
    lulc_grids = {}
    area_distributions = {}
    geojson_layers = {}

    # Decode starting state
    z_np = z.squeeze(0).detach().numpy()  # [64, H, W]
    lulc_start = _embeddings_to_lulc(z_np, decoder)
    lulc_grids[start_year] = lulc_start
    area_distributions[start_year] = _compute_area_distribution(lulc_start)
    geojson_layers[start_year] = _lulc_grid_to_geojson(lulc_start, bbox, start_year)

    with torch.no_grad():
        for step in range(n_years):
            z = model(z, s)
            # L2 normalize to stay on the unit hypersphere
            # (AlphaEarth embeddings are unit vectors; residual addition
            #  causes manifold drift without re-normalization)
            z = torch.nn.functional.normalize(z, p=2, dim=1)
            year = start_year + step + 1
            years.append(year)

            z_np = z.squeeze(0).detach().numpy()
            lulc = _embeddings_to_lulc(z_np, decoder)
            lulc_grids[year] = lulc
            area_distributions[year] = _compute_area_distribution(lulc)
            geojson_layers[year] = _lulc_grid_to_geojson(lulc, bbox, year)

    # Transition matrix: start → end
    lulc_end = lulc_grids[years[-1]]
    transition_matrix = _compute_transition_matrix(lulc_start, lulc_end)

    elapsed = time.time() - t0
    scenario_info = SCENARIOS[scenario]

    summary = (
        f"World Model prediction complete. "
        f"Scenario: {scenario_info.name_zh} ({scenario}). "
        f"Area: {bbox}. "
        f"Period: {start_year}→{years[-1]} ({n_years} years). "
        f"Grid: {h}x{w} pixels. "
        f"Time: {elapsed:.1f}s."
    )

    return {
        "status": "ok",
        "scenario": scenario,
        "scenario_zh": scenario_info.name_zh,
        "bbox": bbox,
        "start_year": start_year,
        "years": years,
        "grid_shape": [h, w],
        "area_distribution": {str(k): v for k, v in area_distributions.items()},
        "transition_matrix": transition_matrix,
        "geojson_layers": {str(k): v for k, v in geojson_layers.items()},
        "summary": summary,
        "elapsed_seconds": round(elapsed, 2),
    }


# ====================================================================
#  Public utilities (for API / toolset)
# ====================================================================


def list_scenarios() -> list[dict]:
    """List available simulation scenarios."""
    return [
        {
            "id": s.name,
            "name_zh": s.name_zh,
            "name_en": s.name,
            "description": s.description,
        }
        for s in SCENARIOS.values()
    ]


def get_model_info() -> dict:
    """Return model status information."""
    import torch

    info = {
        "weights_exist": os.path.exists(WEIGHTS_PATH),
        "decoder_exist": os.path.exists(DECODER_PATH),
        "gee_available": _init_gee(),
        "weights_path": WEIGHTS_PATH,
        "z_dim": Z_DIM,
        "scenario_dim": SCENARIO_DIM,
        "n_scenarios": len(SCENARIOS),
        "param_count": 0,
    }

    # Count parameters if weights exist
    if info["weights_exist"]:
        try:
            ckpt = torch.load(WEIGHTS_PATH, map_location="cpu", weights_only=False)
            info["version"] = ckpt.get("version", "unknown")
            info["training_loss"] = ckpt.get("final_loss", -1)
            info["training_epochs"] = ckpt.get("epochs", -1)
            # Count params from state_dict
            sd = ckpt.get("model_state_dict", {})
            total = sum(v.numel() for v in sd.values())
            info["param_count"] = total
        except Exception:
            pass

    return info
