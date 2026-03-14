"""
GraphRAG — Entity extraction + graph construction + graph-augmented retrieval (v10.0.5).

Combines knowledge base (vector search) with knowledge graph (entity-relationship)
for enhanced RAG retrieval. When a user queries, vector results are augmented
with graph neighbor context for deeper, more connected answers.

All DB operations are non-fatal (never raise to caller).
"""
import json
import re
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .user_context import current_user_id

try:
    from .observability import get_logger
    logger = get_logger("graph_rag")
except Exception:
    import logging
    logger = logging.getLogger("graph_rag")


T_KB_ENTITIES = "agent_kb_entities"
T_KB_RELATIONS = "agent_kb_relations"

# Entity types for GIS domain
ENTITY_TYPES = {"location", "dataset", "metric", "organization", "feature",
                "standard", "coordinate", "method"}


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------

def ensure_graph_rag_tables() -> bool:
    """Create entity and relation tables if not exists."""
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_KB_ENTITIES} (
                    id SERIAL PRIMARY KEY,
                    chunk_id INTEGER NOT NULL,
                    kb_id INTEGER NOT NULL,
                    entity_name VARCHAR(300) NOT NULL,
                    entity_type VARCHAR(50) NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_KB_RELATIONS} (
                    id SERIAL PRIMARY KEY,
                    kb_id INTEGER NOT NULL,
                    source_entity_id INTEGER NOT NULL,
                    target_entity_id INTEGER NOT NULL,
                    relation_type VARCHAR(100) NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
        return True
    except Exception as e:
        logger.warning("Failed to create graph_rag tables: %s", e)
        return False


# ---------------------------------------------------------------------------
# 1. Entity Extraction
# ---------------------------------------------------------------------------

# Regex patterns for common GIS entities
_REGEX_PATTERNS = [
    (r'EPSG:\d{4,5}', "coordinate"),
    (r'(?:WGS|CGCS)\s*\d{2,4}', "coordinate"),
    (r'GB/T\s*\d+', "standard"),
    (r'[\u4e00-\u9fff]{2,8}(?:市|省|县|区|镇|乡|村)', "location"),
    (r'(?:NDVI|DEM|LULC|DTM|DSM)', "metric"),
]


def extract_entities_from_text(chunk_text: str) -> list[dict]:
    """Extract entities from a text chunk using regex patterns.

    Returns list of {name, type, confidence} dicts.
    """
    if not chunk_text:
        return []

    entities = []
    seen = set()

    for pattern, etype in _REGEX_PATTERNS:
        for match in re.finditer(pattern, chunk_text):
            name = match.group().strip()
            if name and name not in seen:
                entities.append({
                    "name": name,
                    "type": etype,
                    "confidence": 0.85,
                })
                seen.add(name)

    return entities


def _llm_extract_entities(chunk_text: str) -> list[dict]:
    """Use Gemini Flash to extract entities from text. Returns list of dicts."""
    try:
        import google.generativeai as genai
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = f"""从以下文本中提取实体。返回JSON数组，每个元素包含:
- name: 实体名称
- type: 实体类型 (location/dataset/metric/organization/feature/standard/coordinate/method)
- confidence: 置信度 (0-1)

只返回JSON数组，不要其他文字。

文本:
{chunk_text[:2000]}"""

        response = model.generate_content(prompt)
        text = response.text.strip()
        # Clean markdown code blocks
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        entities = json.loads(text)
        if isinstance(entities, list):
            return [e for e in entities if isinstance(e, dict) and "name" in e and "type" in e]
    except Exception as e:
        logger.debug("LLM entity extraction failed: %s", e)
    return []


def extract_entities(chunk_text: str, use_llm: bool = True) -> list[dict]:
    """Extract entities using LLM (primary) + regex (fallback/supplement)."""
    entities = []
    seen = set()

    # Try LLM first
    if use_llm:
        llm_entities = _llm_extract_entities(chunk_text)
        for e in llm_entities:
            name = e.get("name", "").strip()
            if name and name not in seen:
                entities.append(e)
                seen.add(name)

    # Supplement with regex
    regex_entities = extract_entities_from_text(chunk_text)
    for e in regex_entities:
        if e["name"] not in seen:
            entities.append(e)
            seen.add(e["name"])

    return entities


# ---------------------------------------------------------------------------
# 2. Entity Deduplication
# ---------------------------------------------------------------------------

def _is_duplicate(name1: str, name2: str, type1: str, type2: str) -> bool:
    """Check if two entities are duplicates (same type + similar name)."""
    if type1 != type2:
        return False
    if name1 == name2:
        return True
    # Fuzzy match threshold
    threshold = 0.85
    ratio = SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
    return ratio >= threshold


def deduplicate_entities(entities: list[dict]) -> list[dict]:
    """Remove near-duplicate entities, keeping highest confidence."""
    if not entities:
        return []

    result = []
    for e in entities:
        is_dup = False
        for existing in result:
            if _is_duplicate(e["name"], existing["name"], e["type"], existing["type"]):
                # Keep higher confidence
                if e.get("confidence", 0) > existing.get("confidence", 0):
                    existing.update(e)
                is_dup = True
                break
        if not is_dup:
            result.append(e)
    return result


# ---------------------------------------------------------------------------
# 3. Graph Construction
# ---------------------------------------------------------------------------

def _save_entities(conn, kb_id: int, chunk_id: int, entities: list[dict]) -> list[int]:
    """Save entities to DB. Returns list of entity IDs."""
    ids = []
    for e in entities:
        result = conn.execute(text(f"""
            INSERT INTO {T_KB_ENTITIES} (chunk_id, kb_id, entity_name, entity_type, confidence)
            VALUES (:chunk_id, :kb_id, :name, :type, :conf)
            RETURNING id
        """), {
            "chunk_id": chunk_id,
            "kb_id": kb_id,
            "name": e["name"],
            "type": e.get("type", "feature"),
            "conf": e.get("confidence", 1.0),
        })
        eid = result.scalar()
        ids.append(eid)
    return ids


def _save_relation(conn, kb_id: int, source_id: int, target_id: int,
                   relation_type: str, confidence: float = 1.0):
    """Save a single relation to DB."""
    conn.execute(text(f"""
        INSERT INTO {T_KB_RELATIONS} (kb_id, source_entity_id, target_entity_id,
                                       relation_type, confidence)
        VALUES (:kb_id, :src, :tgt, :rel, :conf)
    """), {
        "kb_id": kb_id,
        "src": source_id,
        "tgt": target_id,
        "rel": relation_type,
        "conf": confidence,
    })


def build_kb_graph(kb_id: int, use_llm: bool = False) -> dict:
    """Build entity graph for a knowledge base by processing all chunks.

    Returns stats dict with entity/relation counts.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "No database connection"}

    try:
        with engine.connect() as conn:
            # Clear existing entities/relations for this KB
            conn.execute(text(
                f"DELETE FROM {T_KB_RELATIONS} WHERE kb_id = :kb_id"
            ), {"kb_id": kb_id})
            conn.execute(text(
                f"DELETE FROM {T_KB_ENTITIES} WHERE kb_id = :kb_id"
            ), {"kb_id": kb_id})

            # Load all chunks
            chunks = conn.execute(text(
                "SELECT id, content FROM agent_kb_chunks WHERE kb_id = :kb_id ORDER BY id"
            ), {"kb_id": kb_id}).fetchall()

            if not chunks:
                conn.commit()
                return {"status": "ok", "entities": 0, "relations": 0, "message": "No chunks found"}

            # Extract entities from each chunk
            chunk_entities = {}  # chunk_id → list of (entity_id, entity_dict)
            all_entity_ids = []

            for chunk_id, content in chunks:
                entities = extract_entities(content, use_llm=use_llm)
                entities = deduplicate_entities(entities)
                if entities:
                    saved_ids = _save_entities(conn, kb_id, chunk_id, entities)
                    chunk_entities[chunk_id] = list(zip(saved_ids, entities))
                    all_entity_ids.extend(saved_ids)

            # Create co-occurrence relations (entities in same chunk)
            relation_count = 0
            for chunk_id, ent_pairs in chunk_entities.items():
                for i in range(len(ent_pairs)):
                    for j in range(i + 1, len(ent_pairs)):
                        id_a, _ = ent_pairs[i]
                        id_b, _ = ent_pairs[j]
                        _save_relation(conn, kb_id, id_a, id_b, "co_occurs_with", 0.8)
                        relation_count += 1

            conn.commit()

        return {
            "status": "ok",
            "entities": len(all_entity_ids),
            "relations": relation_count,
            "chunks_processed": len(chunks),
        }

    except Exception as e:
        logger.warning("Failed to build KB graph: %s", e)
        return {"status": "error", "message": str(e)}


def incremental_graph_update(kb_id: int, doc_id: int, use_llm: bool = False) -> dict:
    """Process newly added document's chunks and add to existing graph.

    Only processes chunks belonging to doc_id, links to existing entities.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "No database connection"}

    try:
        with engine.connect() as conn:
            chunks = conn.execute(text(
                "SELECT id, content FROM agent_kb_chunks "
                "WHERE kb_id = :kb_id AND doc_id = :doc_id ORDER BY id"
            ), {"kb_id": kb_id, "doc_id": doc_id}).fetchall()

            if not chunks:
                return {"status": "ok", "entities": 0, "relations": 0}

            new_entity_count = 0
            new_relation_count = 0

            for chunk_id, content in chunks:
                entities = extract_entities(content, use_llm=use_llm)
                entities = deduplicate_entities(entities)
                if entities:
                    saved_ids = _save_entities(conn, kb_id, chunk_id, entities)
                    new_entity_count += len(saved_ids)

                    # Co-occurrence within this chunk
                    for i in range(len(saved_ids)):
                        for j in range(i + 1, len(saved_ids)):
                            _save_relation(conn, kb_id, saved_ids[i], saved_ids[j],
                                          "co_occurs_with", 0.8)
                            new_relation_count += 1

            conn.commit()

        return {
            "status": "ok",
            "entities": new_entity_count,
            "relations": new_relation_count,
        }

    except Exception as e:
        logger.warning("Incremental graph update failed: %s", e)
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# 4. Graph-Augmented Retrieval
# ---------------------------------------------------------------------------

def graph_rag_search(
    query: str,
    kb_id: int = None,
    top_k: int = 5,
    expansion_depth: int = 1,
) -> list[dict]:
    """Graph-augmented semantic search.

    1. Vector search → top_k results
    2. Find entities associated with retrieved chunks
    3. Traverse graph to depth expansion_depth
    4. Find chunks containing neighbor entities
    5. Re-rank and combine results

    Returns augmented result list with source tags.
    """
    # Step 1: Standard vector search
    try:
        from .knowledge_base import search_kb
        vector_results = search_kb(query, kb_id=kb_id, top_k=top_k)
    except Exception:
        vector_results = []

    if not vector_results:
        return []

    # Tag vector results
    for r in vector_results:
        r["source"] = "vector"

    # Step 2: Find entities in retrieved chunks
    engine = get_engine()
    if not engine:
        return vector_results

    try:
        chunk_ids = [r["chunk_id"] for r in vector_results if "chunk_id" in r]
        if not chunk_ids:
            return vector_results

        with engine.connect() as conn:
            # Get entities from retrieved chunks
            placeholders = ", ".join(str(int(cid)) for cid in chunk_ids)
            entity_rows = conn.execute(text(
                f"SELECT id, entity_name, entity_type FROM {T_KB_ENTITIES} "
                f"WHERE chunk_id IN ({placeholders})"
            )).fetchall()

            if not entity_rows:
                return vector_results

            entity_ids = [r[0] for r in entity_rows]

            # Step 3: Traverse graph — find neighbor entities
            neighbor_entity_ids = set()
            for _ in range(expansion_depth):
                if not entity_ids:
                    break
                eid_list = ", ".join(str(int(eid)) for eid in entity_ids)
                rel_rows = conn.execute(text(
                    f"SELECT target_entity_id FROM {T_KB_RELATIONS} "
                    f"WHERE source_entity_id IN ({eid_list}) "
                    f"UNION "
                    f"SELECT source_entity_id FROM {T_KB_RELATIONS} "
                    f"WHERE target_entity_id IN ({eid_list})"
                )).fetchall()
                new_ids = {r[0] for r in rel_rows} - set(entity_ids)
                neighbor_entity_ids.update(new_ids)
                entity_ids = list(new_ids)

            if not neighbor_entity_ids:
                return vector_results

            # Step 4: Find chunks containing neighbor entities
            neighbor_eid_list = ", ".join(str(int(eid)) for eid in neighbor_entity_ids)
            neighbor_chunks = conn.execute(text(
                f"SELECT DISTINCT e.chunk_id, c.content "
                f"FROM {T_KB_ENTITIES} e "
                f"JOIN agent_kb_chunks c ON e.chunk_id = c.id "
                f"WHERE e.id IN ({neighbor_eid_list}) "
                f"AND e.chunk_id NOT IN ({placeholders})"
            )).fetchall()

        # Step 5: Build expanded results
        existing_chunk_ids = set(chunk_ids)
        expanded_results = []
        for chunk_id, content in neighbor_chunks:
            if chunk_id not in existing_chunk_ids:
                expanded_results.append({
                    "chunk_id": chunk_id,
                    "content": content[:500] if content else "",
                    "score": 0.7,  # graph expansion score
                    "source": "graph_expansion",
                })
                existing_chunk_ids.add(chunk_id)

        # Combine: vector results first, then graph-expanded
        return vector_results + expanded_results[:top_k]

    except Exception as e:
        logger.warning("Graph RAG search failed: %s", e)
        return vector_results


def get_entity_graph(kb_id: int) -> dict:
    """Export the entity-relationship graph for a KB as node-link data."""
    engine = get_engine()
    if not engine:
        return {"nodes": [], "links": [], "stats": {}}

    try:
        with engine.connect() as conn:
            entities = conn.execute(text(
                f"SELECT id, entity_name, entity_type, confidence "
                f"FROM {T_KB_ENTITIES} WHERE kb_id = :kb_id"
            ), {"kb_id": kb_id}).fetchall()

            relations = conn.execute(text(
                f"SELECT source_entity_id, target_entity_id, relation_type, confidence "
                f"FROM {T_KB_RELATIONS} WHERE kb_id = :kb_id"
            ), {"kb_id": kb_id}).fetchall()

        nodes = [{"id": r[0], "name": r[1], "type": r[2], "confidence": r[3]}
                 for r in entities]
        links = [{"source": r[0], "target": r[1], "type": r[2], "confidence": r[3]}
                 for r in relations]

        # Compute type distribution
        type_counts = {}
        for n in nodes:
            type_counts[n["type"]] = type_counts.get(n["type"], 0) + 1

        return {
            "nodes": nodes,
            "links": links,
            "stats": {
                "node_count": len(nodes),
                "link_count": len(links),
                "entity_types": type_counts,
            },
        }

    except Exception as e:
        logger.warning("Failed to export entity graph: %s", e)
        return {"nodes": [], "links": [], "stats": {}}
