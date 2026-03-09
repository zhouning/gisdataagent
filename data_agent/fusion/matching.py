"""Semantic field matching — 4-tier progressive matching + embedding."""
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Optional

from .constants import UNIT_PATTERNS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding-based Semantic Matching (v7.0)
# ---------------------------------------------------------------------------

_embedding_cache: dict[str, list[float]] = {}
_EMBEDDING_MODEL = "text-embedding-004"


def _get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embedding vectors for field names using Gemini embedding API.

    Uses module-level cache to avoid redundant API calls.
    Returns empty list on failure (graceful degradation).
    """
    uncached = [t for t in texts if t not in _embedding_cache]
    if uncached:
        try:
            from google import genai
            client = genai.Client()
            response = client.models.embed_content(
                model=_EMBEDDING_MODEL,
                contents=uncached,
            )
            for txt, emb in zip(uncached, response.embeddings):
                _embedding_cache[txt] = emb.values
        except Exception as e:
            logger.warning("Embedding API failed: %s — skipping embedding tier", e)
            return []
    return [_embedding_cache.get(t, []) for t in texts]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x ** 2 for x in a) ** 0.5
    norm_b = sum(x ** 2 for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Equivalence Groups
# ---------------------------------------------------------------------------

# Module-level cache for catalog-driven equivalence groups
_catalog_equiv_cache: list[set] | None = None


def _load_catalog_equiv_groups() -> list[set]:
    """Load equivalence groups from semantic_catalog.yaml common_aliases."""
    global _catalog_equiv_cache
    if _catalog_equiv_cache is not None:
        return _catalog_equiv_cache

    try:
        import yaml
        catalog_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "semantic_catalog.yaml",
        )
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = yaml.safe_load(f)

        groups = []
        for domain in catalog.get("domains", []):
            aliases = domain.get("common_aliases", [])
            if len(aliases) >= 2:
                groups.append({a.lower() for a in aliases})
        _catalog_equiv_cache = groups
        return groups
    except Exception:
        _catalog_equiv_cache = []
        return []


def _get_equiv_groups() -> list[set]:
    """Get merged equivalence groups: hardcoded + catalog-driven."""
    hardcoded = [
        {"area", "面积", "zmj", "tbmj", "mj", "shape_area"},
        {"name", "名称", "mc", "dlmc", "qsdwmc", "dkmc"},
        {"code", "编码", "dm", "dlbm", "bm", "dkbm"},
        {"type", "类型", "lx", "dllx", "tdlylx"},
        {"slope", "坡度", "pd", "slope_deg"},
        {"id", "objectid", "fid", "gid", "pkid"},
        {"population", "人口", "rk", "rksl", "pop"},
        {"address", "地址", "dz", "addr", "location"},
        {"elevation", "高程", "dem", "gc", "alt", "height"},
        {"perimeter", "周长", "zc", "shape_length"},
    ]

    catalog_groups = _load_catalog_equiv_groups()

    # Merge: if a catalog group overlaps with a hardcoded group, union them
    merged = [set(g) for g in hardcoded]
    for cg in catalog_groups:
        found_overlap = False
        for mg in merged:
            if mg & cg:
                mg |= cg
                found_overlap = True
                break
        if not found_overlap:
            merged.append(set(cg))

    return merged


# ---------------------------------------------------------------------------
# Tokenization and Similarity
# ---------------------------------------------------------------------------

def _tokenize_field_name(name: str) -> list[str]:
    """Split a field name into tokens by underscore, camelCase, and digit boundaries.

    Examples:
        "land_use_type" → ["land", "use", "type"]
        "landUseType"   → ["land", "use", "type"]
        "area2d"        → ["area", "2", "d"]
    """
    # Split by underscores first
    parts = name.replace("-", "_").split("_")
    tokens = []
    for part in parts:
        # Split camelCase and digit boundaries
        sub = re.sub(r"([a-z])([A-Z])", r"\1_\2", part)
        sub = re.sub(r"([A-Za-z])(\d)", r"\1_\2", sub)
        sub = re.sub(r"(\d)([A-Za-z])", r"\1_\2", sub)
        tokens.extend(t.lower() for t in sub.split("_") if t)
    return tokens


def _tokenized_similarity(name_a: str, name_b: str) -> float:
    """Compute similarity between two field names using tokenized comparison.

    Weighted blend: 60% Jaccard token overlap + 40% SequenceMatcher ratio.
    """
    tokens_a = set(_tokenize_field_name(name_a))
    tokens_b = set(_tokenize_field_name(name_b))

    if not tokens_a or not tokens_b:
        return 0.0

    # Jaccard
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    jaccard = intersection / union if union > 0 else 0.0

    # SequenceMatcher on full name
    seq_ratio = SequenceMatcher(None, name_a.lower(), name_b.lower()).ratio()

    return 0.6 * jaccard + 0.4 * seq_ratio


def _types_compatible(dtype_a: str, dtype_b: str) -> bool:
    """Check if two column data types are compatible for semantic matching.

    Prevents numeric fields from matching text fields (e.g., slope vs slope_type).
    """
    if not dtype_a or not dtype_b:
        return True  # unknown types → allow match

    numeric_indicators = {"int", "float", "double", "numeric", "decimal", "number"}
    text_indicators = {"object", "str", "string", "text", "char", "varchar", "category"}

    a_lower = dtype_a.lower()
    b_lower = dtype_b.lower()

    a_numeric = any(ind in a_lower for ind in numeric_indicators)
    b_numeric = any(ind in b_lower for ind in numeric_indicators)
    a_text = any(ind in a_lower for ind in text_indicators)
    b_text = any(ind in b_lower for ind in text_indicators)

    # Block numeric↔text mismatches
    if (a_numeric and b_text) or (a_text and b_numeric):
        return False

    return True


# ---------------------------------------------------------------------------
# Unit Detection
# ---------------------------------------------------------------------------

def _detect_unit(column_name: str) -> Optional[str]:
    """Detect measurement unit from column name using UNIT_PATTERNS.

    Returns unit key (e.g., 'mu', 'm2', 'ha') or None.
    """
    col_lower = column_name.lower()
    for unit_key, patterns in UNIT_PATTERNS.items():
        for pattern in patterns:
            if pattern.lower() in col_lower:
                return unit_key
    return None


def _strip_unit_suffix(column_name: str) -> str:
    """Strip unit-related suffix from column name to get base semantic name."""
    col_lower = column_name.lower()
    for patterns in UNIT_PATTERNS.values():
        for pattern in patterns:
            p = pattern.lower()
            if col_lower.endswith(p):
                base = col_lower[:-len(p)].rstrip("_- ")
                if base:
                    return base
    return col_lower


# ---------------------------------------------------------------------------
# Main Field Matching
# ---------------------------------------------------------------------------

def _find_field_matches(
    sources,
    use_embedding: bool = False,
    use_llm_schema: bool = False,
) -> list[dict]:
    """Find semantically matching fields across sources.

    Uses progressive semantic matching tiers:
      1. Exact match (case-insensitive) — confidence 1.0
      2. Equivalence group match (hardcoded + catalog-driven) — confidence 0.8
      2.5a. LLM schema alignment (opt-in, replaces tiers 2.5b-4) — confidence from LLM
      2.5b. Embedding match (Gemini text-embedding-004, opt-in) — confidence 0.78
      3. Unit-aware matching — confidence 0.75
      4. Tokenized fuzzy match with type compatibility — confidence 0.5-0.7

    When use_llm_schema=True, Tier 1 (exact) runs first, then unmatched fields
    go to LLM schema alignment, bypassing Tiers 2-4.
    """
    if len(sources) < 2:
        return []

    matches = []
    left_cols = {c["name"].lower(): c["name"] for c in sources[0].columns}
    right_cols = {c["name"].lower(): c["name"] for c in sources[1].columns}

    # Build dtype maps for type compatibility checking
    left_dtypes = {c["name"].lower(): c.get("dtype", "") for c in sources[0].columns}
    right_dtypes = {c["name"].lower(): c.get("dtype", "") for c in sources[1].columns}

    # Tier 1: Exact match (case-insensitive) — always runs first
    matched_right = set()
    for lk, lv in left_cols.items():
        if lk in right_cols:
            matches.append({"left": lv, "right": right_cols[lk], "confidence": 1.0})
            matched_right.add(lk)

    # Tier 2 LLM shortcut: if use_llm_schema, send unmatched fields to LLM
    # and skip heuristic tiers 2-4
    if use_llm_schema:
        unmatched_left_llm = [c for c in sources[0].columns
                              if c["name"].lower() not in
                              {m["left"].lower() for m in matches}]
        unmatched_right_llm = [c for c in sources[1].columns
                               if c["name"].lower() not in matched_right]
        if unmatched_left_llm and unmatched_right_llm:
            from .schema_alignment import llm_align_schemas
            llm_matches = llm_align_schemas(unmatched_left_llm, unmatched_right_llm)
            for lm in llm_matches:
                if lm["right"].lower() not in matched_right:
                    matches.append(lm)
                    matched_right.add(lm["right"].lower())
        return matches

    # Tier 2: Known equivalence patterns (hardcoded + catalog-driven)
    equiv_groups = _get_equiv_groups()

    for group in equiv_groups:
        left_hit = [(lk, lv) for lk, lv in left_cols.items() if lk in group]
        right_hit = [(rk, rv) for rk, rv in right_cols.items()
                     if rk in group and rk not in matched_right]
        for rk, rv in right_hit:
            for _, lv in left_hit:
                if lv.lower() != rv.lower():
                    matches.append({"left": lv, "right": rv, "confidence": 0.8})
                    matched_right.add(rk)
                    break

    # Tier 2.5: Embedding-based semantic matching (opt-in, Gemini API)
    if use_embedding:
        unmatched_left_emb = {lk: lv for lk, lv in left_cols.items()
                              if not any(m["left"].lower() == lk for m in matches)}
        unmatched_right_emb = {rk: rv for rk, rv in right_cols.items()
                               if rk not in matched_right}
        if unmatched_left_emb and unmatched_right_emb:
            left_texts = [f"{lv} ({left_dtypes.get(lk, '')})"
                          for lk, lv in unmatched_left_emb.items()]
            right_texts = [f"{rv} ({right_dtypes.get(rk, '')})"
                           for rk, rv in unmatched_right_emb.items()]
            left_embeddings = _get_embeddings(left_texts)
            right_embeddings = _get_embeddings(right_texts)

            if left_embeddings and right_embeddings:
                left_keys = list(unmatched_left_emb.keys())
                right_keys = list(unmatched_right_emb.keys())
                for i, lk in enumerate(left_keys):
                    if not left_embeddings[i]:
                        continue
                    best_sim = 0.0
                    best_rk = None
                    for j, rk in enumerate(right_keys):
                        if rk in matched_right or not right_embeddings[j]:
                            continue
                        if not _types_compatible(
                            left_dtypes.get(lk, ""), right_dtypes.get(rk, "")
                        ):
                            continue
                        sim = _cosine_similarity(
                            left_embeddings[i], right_embeddings[j]
                        )
                        if sim > best_sim and sim >= 0.75:
                            best_sim = sim
                            best_rk = rk
                    if best_rk is not None:
                        matches.append({
                            "left": unmatched_left_emb[lk],
                            "right": unmatched_right_emb[best_rk],
                            "confidence": 0.78,
                            "match_type": "embedding",
                            "similarity": round(best_sim, 3),
                        })
                        matched_right.add(best_rk)

    # Tier 3: Unit-aware matching
    for lk, lv in left_cols.items():
        if any(m["left"].lower() == lk for m in matches):
            continue
        for rk, rv in right_cols.items():
            if rk in matched_right:
                continue
            left_unit = _detect_unit(lk)
            right_unit = _detect_unit(rk)
            if left_unit and right_unit and left_unit != right_unit:
                left_base = _strip_unit_suffix(lk)
                right_base = _strip_unit_suffix(rk)
                if left_base and right_base:
                    base_ratio = SequenceMatcher(None, left_base, right_base).ratio()
                    if base_ratio >= 0.6:
                        matches.append({
                            "left": lv, "right": rv, "confidence": 0.75,
                            "match_type": "unit_aware",
                            "left_unit": left_unit, "right_unit": right_unit,
                        })
                        matched_right.add(rk)

    # Tier 4: Tokenized fuzzy matching with type compatibility
    unmatched_left = {lk: lv for lk, lv in left_cols.items()
                      if not any(m["left"].lower() == lk for m in matches)}
    unmatched_right = {rk: rv for rk, rv in right_cols.items()
                       if rk not in matched_right}

    for lk, lv in unmatched_left.items():
        if len(lk) < 3:
            continue
        best_score = 0.0
        best_rk = None
        for rk, rv in unmatched_right.items():
            if len(rk) < 3:
                continue
            # Type compatibility gate
            if not _types_compatible(left_dtypes.get(lk, ""), right_dtypes.get(rk, "")):
                continue
            # Use original names for tokenization (preserves camelCase)
            score = _tokenized_similarity(lv, unmatched_right[rk])
            if score > best_score and score >= 0.65:
                best_score = score
                best_rk = rk
        if best_rk is not None:
            confidence = round(0.5 + best_score * 0.2, 2)
            matches.append({
                "left": lv, "right": unmatched_right[best_rk],
                "confidence": confidence, "match_type": "fuzzy",
            })
            matched_right.add(best_rk)

    return matches
