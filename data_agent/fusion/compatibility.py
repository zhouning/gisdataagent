"""Compatibility assessment between data sources."""
from shapely.geometry import box

from .models import FusionSource, CompatibilityReport
from .constants import STRATEGY_MATRIX
from .matching import _find_field_matches


def assess_compatibility(
    sources: list[FusionSource],
    use_embedding: bool = False,
    use_llm_schema: bool = False,
) -> CompatibilityReport:
    """Assess fusion compatibility between data sources.

    Checks CRS consistency, spatial overlap, and field semantic matches.
    """
    if len(sources) < 2:
        return CompatibilityReport(
            warnings=["Need at least 2 data sources to assess compatibility"],
            overall_score=0.0,
        )

    warnings = []

    # --- CRS compatibility ---
    crs_set = {s.crs for s in sources if s.crs is not None}
    crs_compatible = len(crs_set) <= 1
    if not crs_compatible:
        warnings.append(f"CRS mismatch: {crs_set}. Auto-reprojection will be applied.")

    # --- Spatial overlap (IoU on bounding boxes) ---
    spatial_iou = _compute_spatial_overlap(sources)
    if spatial_iou < 0.01:
        no_bounds = [s for s in sources if s.bounds is None]
        has_bounds = [s for s in sources if s.bounds is not None]
        if len(has_bounds) >= 2:
            warnings.append("Very low spatial overlap between sources.")

    # --- Field semantic matching ---
    field_matches = _find_field_matches(
        sources, use_embedding=use_embedding, use_llm_schema=use_llm_schema
    )

    # --- Recommended strategies ---
    type_pair = (sources[0].data_type, sources[1].data_type)
    recommended = STRATEGY_MATRIX.get(type_pair, [])
    if not recommended:
        # Try reverse pair
        type_pair_rev = (sources[1].data_type, sources[0].data_type)
        recommended = STRATEGY_MATRIX.get(type_pair_rev, [])
    if not recommended:
        warnings.append(f"No built-in strategy for {type_pair[0]}+{type_pair[1]}. Manual strategy needed.")

    # --- Overall score ---
    score = 0.0
    if crs_compatible:
        score += 0.3
    elif len(crs_set) > 0:
        score += 0.15  # fixable via reprojection
    if spatial_iou > 0.1:
        score += 0.3
    elif any(s.data_type == "tabular" for s in sources):
        score += 0.2  # tabular doesn't need spatial overlap
    if field_matches:
        score += 0.2
    if recommended:
        score += 0.2
    score = min(score, 1.0)

    return CompatibilityReport(
        crs_compatible=crs_compatible,
        spatial_overlap_iou=round(spatial_iou, 4),
        field_matches=field_matches,
        overall_score=round(score, 2),
        recommended_strategies=recommended,
        warnings=warnings,
    )


def _compute_spatial_overlap(sources: list[FusionSource]) -> float:
    """Compute IoU of bounding boxes between first two sources with bounds."""
    bounded = [s for s in sources if s.bounds is not None]
    if len(bounded) < 2:
        return 0.0

    b1 = box(*bounded[0].bounds)
    b2 = box(*bounded[1].bounds)

    if not b1.intersects(b2):
        return 0.0

    intersection = b1.intersection(b2).area
    union = b1.union(b2).area
    return intersection / union if union > 0 else 0.0
