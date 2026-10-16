"""Rank governed meanings within the permission-filtered NL2SQL catalog.

The index contains source metadata and metric definitions, never reference
questions or SQL answers. BM25 recalls descriptions as well as identifiers;
exact aliases get an independent boost. The complete authorized schema stays
available so a low-ranked bridge or field is not lost.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter

from .nl2sql_prompt_metadata import field_prompt_annotations, field_prompt_description
from .nl2sql_observability import observe_stage, annotate_stage

_STOPWORDS = set("a an and are as at be by did do does for from give has have how in is it list many of on or please provide that the their them these this to was were what when which who with without".split())
_RETRIEVAL_VERSION = "governed-bm25-alias-v7"

# Chinese questions rarely repeat a governed alias character-for-character.
# These are deliberately small, business-language normalizations rather than
# a general purpose word segmenter.  They make expressions such as
# ``男性客户占全部客户的比例`` comparable with the registered alias
# ``男性客户占比`` while preserving the entity words that distinguish two
# metrics in the same source.
_CJK_SYNONYMS = (
    ("百分比", "比例"), ("百分率", "比例"), ("百分数", "比例"),
    ("比率", "比例"), ("占比", "比例"), ("份额", "比例"),
    ("获胜次数", "胜数量"), ("获胜场次", "胜数量"),
    ("胜场数", "胜数量"), ("胜场次数", "胜数量"),
    ("场次数", "数量"), ("比赛场次", "数量"), ("场数", "数量"),
    ("场次", "数量"),
    ("次数", "数量"), ("个数", "数量"), ("数目", "数量"),
    ("总数", "数量"), ("人数", "数量"), ("病人", "患者"),
    ("顾客", "客户"), ("获胜", "胜"), ("胜利", "胜"),
    ("赢球", "胜"), ("赢得", "胜"), ("打平", "平局"),
    ("平手", "平局"),
)
_CJK_GRAMMAR = (
    "请问", "查询", "统计", "列出", "显示", "共有", "一共有", "总共有",
    "分别", "各自", "其中", "全部", "所有", "每个", "每名", "的",
    "吗", "呢", "请", "一下",
)


def _normalize_cjk_semantics(text: str) -> str:
    """Return a compact semantic form for Chinese alias matching.

    This intentionally does not feed the LLM or alter SQL generation.  It is
    only an evidence extractor used to decide whether a registered alias was
    expressed in a natural question.  Keeping the transformation local makes
    the original question and governed definitions auditable.
    """
    value = re.sub(r"\s+", "", str(text or "").casefold())
    if not value:
        return ""
    # A ratio question commonly inserts a denominator between the subject and
    # the measure (``A 占全部 B 的比例``).  Preserve the subject and collapse
    # that grammatical construction to the governed measure word.
    value = re.sub(
        r"占[^，。；、,;!?！？]*?的(?:百分比|百分率|比率|占比|比例|率)",
        "比例", value,
    )
    # ``共有多少名患者`` and ``多少个客户`` express a count with the noun
    # after the interrogative.  Move the canonical quantity marker after the
    # noun so it can match aliases such as ``患者数量`` and ``客户数``.
    value = re.sub(
        r"多少(?:个|名|场|次|条|家|种)?([\u4e00-\u9fff]{1,8})",
        r"\1数量", value,
    )
    value = value.replace("是多少", "").replace("多少", "数量")
    for source, target in _CJK_SYNONYMS:
        value = value.replace(source, target)
    # Units and a few common nouns add no metric meaning in these aliases.
    value = value.replace("比赛数量", "数量")
    value = value.replace("数", "数量")
    for word in _CJK_GRAMMAR:
        value = value.replace(word, "")
    value = re.sub(r"[，。；、,;!?！？：:]", "", value)
    value = value.replace("数量量", "数量")
    return value


def _cjk_alias_match_score(question: str, alias: str) -> float:
    """Return semantic coverage in ``[0, 1]`` for a Chinese alias.

    Exact normalized phrases receive 1.0.  For coordinated questions (for
    example, asking for home wins, away wins and draws together), bigram
    coverage handles the intervening conjunctions without accepting a single
    generic word such as ``数量`` as evidence by itself.
    """
    normalized_question = _normalize_cjk_semantics(question)
    normalized_alias = _normalize_cjk_semantics(alias)
    if not normalized_question or not normalized_alias:
        return 0.0
    if normalized_alias in normalized_question:
        return 1.0
    # Compare the entity stem before the generic measure marker.  Without
    # this guard ``客户数量`` can incorrectly match ``账户数量`` because both
    # share the suffix ``户数量``.
    markers = ("数量", "比例")
    alias_stem = normalized_alias
    question_stem = normalized_question
    for marker in markers:
        if marker in alias_stem:
            alias_stem = alias_stem.split(marker, 1)[0]
            break
    for marker in markers:
        if marker in question_stem:
            question_stem = question_stem.split(marker, 1)[0]
            break
    if alias_stem and question_stem and alias_stem not in question_stem and question_stem not in alias_stem:
        return 0.0
    if len(normalized_alias) < 4:
        return 0.0
    alias_bigrams = {normalized_alias[i:i + 2] for i in range(len(normalized_alias) - 1)}
    question_bigrams = {normalized_question[i:i + 2] for i in range(len(normalized_question) - 1)}
    if not alias_bigrams:
        return 0.0
    coverage = len(alias_bigrams & question_bigrams) / len(alias_bigrams)
    # Require at least one non-generic entity/measure pair.  This prevents a
    # bare ``数量`` alias from tagging every count metric.
    informative = [bigram for bigram in alias_bigrams if bigram not in {"数量", "比例"}]
    informative_hit = sum(bigram in question_bigrams for bigram in informative)
    if coverage >= 0.66 and informative_hit >= 1:
        return round(coverage, 6)
    return 0.0


def _ascii_alias_match_score(question: str, alias: str) -> float:
    """Match a multi-word English alias when words are separated naturally."""
    alias_tokens = [token for token in _tokens(alias) if token not in _STOPWORDS]
    question_tokens = set(_tokens(question))
    if len(alias_tokens) < 2 or not question_tokens:
        return 0.0
    coverage = sum(token in question_tokens for token in alias_tokens) / len(alias_tokens)
    return round(coverage, 6) if coverage >= 0.75 else 0.0


def semantic_retrieval_enabled() -> bool:
    value = os.environ.get("GDA_NL2SQL_SEMANTIC_RETRIEVAL", "0").strip().casefold()
    if value in {"0", "false", "off", "no", ""}:
        return False
    if value in {"1", "true", "on", "yes"}:
        return True
    raise ValueError("GDA_NL2SQL_SEMANTIC_RETRIEVAL must be a boolean")


def _tokens(text: str) -> list[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).casefold()
    parts = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text)
    result = []
    for part in parts:
        if part in _STOPWORDS:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            result.extend(part[i:i+2] for i in range(max(1, len(part)-1)))
            continue
        # Conservative plural normalization keeps technical terms and codes.
        if len(part) > 5 and part.endswith("ies"):
            part = part[:-3] + "y"
        elif len(part) > 4 and part.endswith("s") and not part.endswith(("ss", "us", "is")):
            part = part[:-1]
        result.append(part)
    return result


def _phrase_match(question: str, alias: str) -> bool:
    alias = str(alias).strip().casefold()
    if not alias or alias in _STOPWORDS:
        return False
    if re.search(r"[\u4e00-\u9fff]", alias):
        return alias in question.casefold()
    return bool(re.search(r"(?<![a-z0-9_])" + re.escape(alias) + r"(?![a-z0-9_])", question.casefold()))


def _cjk_alias_matches(question: str, alias: str) -> bool:
    """Match Chinese business aliases inside natural Chinese questions.

    Chinese has no whitespace token boundary, so the ASCII word-boundary
    matcher is intentionally bypassed for CJK aliases.  The surrounding
    question may include grammatical suffixes such as ``是多少`` or ``占比``.
    """
    alias = str(alias).strip().casefold()
    return bool(alias and re.search(r"[\u4e00-\u9fff]", alias) and (
        alias in question.casefold() or _cjk_alias_match_score(question, alias) >= 0.66
    ))


@observe_stage("retrieval.bm25")
def rank_documents(question: str, documents: list[dict]) -> list[dict]:
    """Stable scores with matched terms for inspection; scores are not confidence."""
    if not documents:
        return []
    counters = [Counter(_tokens(d.get("search_text") or "")) for d in documents]
    frequencies = Counter(term for counter in counters for term in counter)
    average = sum(sum(c.values()) for c in counters) / len(counters) or 1
    terms = set(_tokens(question))
    result = []
    for document, counts in zip(documents, counters):
        score = 0.0
        matched = sorted(terms & counts.keys())
        length = sum(counts.values())
        for term in matched:
            idf = math.log(1 + (len(documents) - frequencies[term] + .5) / (frequencies[term] + .5))
            tf = counts[term]
            score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / average))
        aliases = []
        alias_scores = {}
        for raw_alias in document.get("aliases") or []:
            alias = str(raw_alias)
            exact = _phrase_match(question, alias)
            is_cjk = bool(re.search(r"[\u4e00-\u9fff]", alias))
            cjk_score = _cjk_alias_match_score(question, alias) if is_cjk else 0.0
            ascii_score = _ascii_alias_match_score(question, alias) if not is_cjk else 0.0
            alias_score = max(cjk_score, ascii_score)
            if exact or alias_score >= 0.66:
                aliases.append(alias)
                alias_scores[alias] = alias_score
        aliases = sorted(set(aliases))
        score += sum(2 + min(len(_tokens(a)), 4) + alias_scores.get(a, 0.0) for a in aliases)
        if score > 0:
            result.append({**document, "score": round(score, 6), "matched_terms": matched,
                           "matched_aliases": aliases,
                           "matched_alias_scores": {a: round(alias_scores.get(a, 0.0), 6) for a in aliases}})
    return sorted(result, key=lambda d: (-d["score"], d["id"]))


def rank_metrics(question: str, metrics: list[dict]) -> list[dict]:
    # Catalog descriptions append grain, aggregation and population contracts.
    # Those remain in the returned hit and prompt, but their generic warnings
    # and lists of related fields are poor evidence that a metric is requested.
    # Rank by the metric's meaning and aliases rather than its audit/contract
    # boilerplate (e.g. an eye-colour join warning in a row-count contract).
    documents = [{"id": m["source_scope"] + ":" + m["name"],
                  "aliases": [m["name"], *(m.get("aliases") or [])],
                  "search_text": " ".join([m["name"], (m.get("description") or "").split(" Grain:", 1)[0], " ".join(m.get("aliases") or [])]),
                  "metric": m} for m in metrics]
    ranked = rank_documents(question, documents)
    # Prefer a governed business metric over a generic physical row count when
    # both expose the same alias.  The distinction matters for BIRD tables
    # with repeated examination/laboratory observations and for metrics such
    # as distinct patients or conditional client counts.
    for item in ranked:
        metric = item["metric"]
        name = str(metric.get("name") or "")
        if name.casefold().endswith("_record_count"):
            aliases = set(item.get("matched_aliases") or [])
            if aliases and any(
                other["metric"] is not metric
                and aliases.intersection(other.get("matched_aliases") or [])
                and not str(other["metric"].get("name") or "").casefold().endswith("_record_count")
                for other in ranked
            ):
                item["score"] = round(float(item.get("score") or 0.0) - 0.75, 6)
    ranked.sort(key=lambda d: (-d["score"], d["id"]))
    return [{**d["metric"], "retrieval": {k: d[k] for k in ("score", "matched_terms", "matched_aliases", "matched_alias_scores")}}
            for d in ranked]


def select_metric_hits(question: str, metrics: list[dict], *, limit: int = 6) -> list[dict]:
    """Select only metrics evidenced by the question when aliases are clear.

    A source-scoped registry can contain dozens of valid formulas. Sending all
    of them to the model creates an avoidable choice problem. Alias evidence
    is stronger than generic BM25 overlap: retain up to three directly
    requested metrics (enough for coordinated requests such as home/away/draw
    counts), and fall back to the normal top-six alternatives only when no
    governed alias is expressed.
    """
    ranked = rank_metrics(question, metrics)
    if not ranked:
        return []
    evidenced = [hit for hit in ranked if hit.get("retrieval", {}).get("matched_aliases")]
    if evidenced:
        top_score = float(evidenced[0].get("retrieval", {}).get("score") or 0.0)
        selected = [hit for hit in evidenced
                    if float(hit.get("retrieval", {}).get("score") or 0.0) >= max(1.0, top_score * 0.48)][:3]
        for hit in selected:
            retrieval = hit.setdefault("retrieval", {})
            alias_scores = retrieval.get("matched_alias_scores") or {}
            retrieval["metric_confidence"] = round(max(alias_scores.values() or [0.0]), 6)
            retrieval["metric_selection_reason"] = "governed_alias_match"
        return selected
    for hit in ranked[:limit]:
        retrieval = hit.setdefault("retrieval", {})
        retrieval["metric_confidence"] = 0.0
        retrieval["metric_selection_reason"] = "bm25_fallback"
    return ranked[:limit]


@observe_stage("semantic.retrieve")
def retrieve_semantics(payload: dict, metrics: list[dict]) -> dict:
    question = str(payload.get("user_question") or "")
    documents = []
    table_documents = []
    for table in payload.get("candidate_tables") or []:
        name = table["table_name"]
        # Grounding normalizes registered business names into table_aliases;
        # synonyms is retained for callers supplying the older catalog shape.
        # Read only the already authorized candidates and never mutate them.
        table_aliases = list(dict.fromkeys(str(value).strip() for value in [
            name.rsplit(".", 1)[-1], table.get("display_name") or "",
            *(table.get("table_aliases") or []), *(table.get("synonyms") or []),
        ] if str(value or "").strip()))
        table_documents.append({"id": name, "table": name,
            "description": table.get("description") or "",
            "primary_keys": table.get("primary_keys") or [],
            "aliases": table_aliases,
            "search_text": " ".join([" ".join(table_aliases), table.get("description") or ""])})
        for column in table.get("columns") or []:
            aliases, values = field_prompt_annotations(column)
            description = field_prompt_description(column)
            ref = name + "." + column["column_name"]
            documents.append({"id": ref, "table": name, "field": column["column_name"],
                "aliases": [column["column_name"], *aliases],
                "description": description, "value_semantics": values,
                "search_text": " ".join([column["column_name"], " ".join(aliases), description,
                                          json.dumps(values, ensure_ascii=False)])})
    ranked = rank_documents(question, documents)
    annotate_stage(field_count=len(documents), metric_count=len(metrics),
                   candidate_count=len(table_documents), version=_RETRIEVAL_VERSION)
    hits = [{key: d[key] for key in ("id", "table", "field", "description", "value_semantics",
                                    "score", "matched_terms", "matched_aliases")} for d in ranked[:16]]
    metric_hits = select_metric_hits(question, metrics)
    table_hits = [{k: d[k] for k in ("id", "table", "description", "primary_keys", "score", "matched_terms", "matched_aliases")}
                  for d in rank_documents(question, table_documents)[:6]]
    tables = sorted({d["table"] for d in hits + table_hits} | {m["source_scope"] for m in metric_hits})
    # Same-scope relationships stay available even when their join keys have
    # no lexical overlap with the question. Never invent a path from proximity.
    joins = (payload.get("warehouse_join_hints") or {}).get("join_paths") or []
    fingerprint = hashlib.sha256(json.dumps({"fields": documents, "tables": table_documents, "metrics": metrics, "joins": joins},
                                            ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    from .nl2sql_field_roles import field_role_candidates
    from .nl2sql_value_presence import requested_value_presence
    from .nl2sql_relationship_retrieval import retrieve_relationships
    relationship_context = retrieve_relationships(question, payload.get("candidate_tables") or [], tables)
    fingerprint = hashlib.sha256((fingerprint + relationship_context["catalog_sha256"]).encode()).hexdigest()
    return {"version": _RETRIEVAL_VERSION, "catalog_sha256": fingerprint,
            "indexed_fields": len(documents), "authorized_metric_count": len(metrics),
            "field_hits": hits, "table_hits": table_hits, "metric_hits": metric_hits, "relevant_tables": tables,
            "registered_join_paths": joins,
            "relationship_context": relationship_context,
            "field_role_candidates": field_role_candidates(payload),
            "value_presence_requests": requested_value_presence(question, payload),
            "limitations": "Retrieval scores rank text relevance; they do not prove a semantic mapping is correct. Full authorized schema is retained."}


def retrieval_prompt(packet: dict) -> str:
    from .nl2sql_field_roles import field_role_guidance
    from .nl2sql_relationship_retrieval import relationship_guidance
    from .nl2sql_value_presence import value_presence_guidance
    return ("\n## Question-matched governed meanings\n"
            "Use these retrieved definitions to resolve field meanings, code values, metric grain and population. "
            "A hit is a candidate, not a forced interpretation. Check the question against its definition and choose "
            "the exact requested meaning. Distinguish similar fields in different tables; use the documented "
            "relationship that represents the requested business role. If an expression is used, preserve its "
            "aggregation, denominator population, NULL policy and unit. Do not treat a retrieval score as certainty. "
            "The complete authorized catalog remains below for alternatives and bridge fields.\n"
            + json.dumps({k: packet[k] for k in ("table_hits", "field_hits", "metric_hits", "registered_join_paths")}, ensure_ascii=False)
            + "\n" + field_role_guidance(packet.get("field_role_candidates") or [])
            + value_presence_guidance(packet.get("value_presence_requests") or [])
            + relationship_guidance(packet.get("relationship_context") or {}))
