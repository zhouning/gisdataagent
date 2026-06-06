"""Default review-template read model for Standards Platform."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine


TEMPLATE_ID = "default_review_v1"
STEP_IDS = (
    "draft",
    "start_review",
    "audit_references",
    "resolve_comments",
    "close_round",
    "approved",
)
COMPLETE_VERSION_STATUSES = {"approved", "released", "retired"}


def default_review_template(version_id: str) -> dict[str, Any]:
    """Return the deterministic default review workflow for a version.

    This is a read-only projection over the existing review state machine.
    It does not persist templates or introduce any new workflow semantics.
    """
    eng = get_engine()
    with eng.connect() as conn:
        version = conn.execute(text("""
            SELECT v.id, v.status, v.version_label, v.document_id,
                   d.doc_code, d.title
              FROM std_document_version v
              JOIN std_document d ON d.id = v.document_id
             WHERE v.id = :v
        """), {"v": version_id}).mappings().first()
        if version is None:
            raise LookupError("version not found")

        open_round = conn.execute(text("""
            SELECT id, document_version_id, reviewer_user_id, initiated_by,
                   initiated_at, closed_at, status, outcome
              FROM std_review_round
             WHERE document_version_id = :v AND status = 'open'
             ORDER BY initiated_at DESC
             LIMIT 1
        """), {"v": version_id}).mappings().first()
        latest_round = conn.execute(text("""
            SELECT id, document_version_id, reviewer_user_id, initiated_by,
                   initiated_at, closed_at, status, outcome
              FROM std_review_round
             WHERE document_version_id = :v
             ORDER BY initiated_at DESC
             LIMIT 1
        """), {"v": version_id}).mappings().first()

        refs = conn.execute(text("""
            SELECT count(*) AS total_refs,
                   count(*) FILTER
                       (WHERE r.verification_status = 'pending') AS pending_refs,
                   count(*) FILTER
                       (WHERE r.verification_status = 'approved') AS approved_refs,
                   count(*) FILTER
                       (WHERE r.verification_status = 'rejected') AS rejected_refs
              FROM std_reference r
              JOIN std_clause c ON c.id = r.source_clause_id
             WHERE c.document_version_id = :v
        """), {"v": version_id}).mappings().one()

        comment_round_id = (
            str(open_round["id"]) if open_round is not None
            else str(latest_round["id"]) if latest_round is not None
            else None
        )
        comments = _comment_counts(conn, comment_round_id)

    version_status = version["status"]
    latest = dict(latest_round) if latest_round is not None else None
    current = dict(open_round) if open_round is not None else None
    ref_metrics = {k: int(refs[k] or 0) for k in refs.keys()}
    comment_metrics = {k: int(comments[k] or 0) for k in comments.keys()}
    blocking = (
        current is not None
        and (ref_metrics["pending_refs"] > 0
             or comment_metrics["open_comments"] > 0)
    )
    statuses = _step_statuses(
        version_status=version_status,
        has_open_round=current is not None,
        has_latest_round=latest is not None,
        latest_round_outcome=latest["outcome"] if latest else None,
        pending_refs=ref_metrics["pending_refs"],
        open_comments=comment_metrics["open_comments"],
    )

    summary = {
        "open_round_id": str(current["id"]) if current else None,
        "latest_round_id": str(latest["id"]) if latest else None,
        "latest_round_status": latest["status"] if latest else None,
        "latest_round_outcome": latest["outcome"] if latest else None,
        "reviewer_user_id": (
            current["reviewer_user_id"] if current
            else latest["reviewer_user_id"] if latest else None
        ),
        "pending_refs": ref_metrics["pending_refs"],
        "approved_refs": ref_metrics["approved_refs"],
        "rejected_refs": ref_metrics["rejected_refs"],
        "total_refs": ref_metrics["total_refs"],
        "open_comments": comment_metrics["open_comments"],
        "resolved_comments": comment_metrics["resolved_comments"],
        "total_comments": comment_metrics["total_comments"],
        "blocking": blocking,
    }

    return {
        "template_id": TEMPLATE_ID,
        "version_id": version_id,
        "version_status": version_status,
        "steps": _steps(statuses, version, current, latest,
                        ref_metrics, comment_metrics, blocking),
        "edges": _edges(),
        "summary": summary,
    }


def _comment_counts(conn, round_id: str | None) -> dict[str, int]:
    if round_id is None:
        return {"total_comments": 0, "open_comments": 0,
                "resolved_comments": 0}
    return dict(conn.execute(text("""
        SELECT count(*) AS total_comments,
               count(*) FILTER (WHERE resolution = 'open') AS open_comments,
               count(*) FILTER (WHERE resolution != 'open') AS resolved_comments
          FROM std_review_comment
         WHERE round_id = :r
    """), {"r": round_id}).mappings().one())


def _step_statuses(*, version_status: str, has_open_round: bool,
                   has_latest_round: bool, latest_round_outcome: str | None,
                   pending_refs: int, open_comments: int) -> dict[str, str]:
    if version_status in COMPLETE_VERSION_STATUSES:
        return {step_id: "done" for step_id in STEP_IDS}

    if version_status == "review":
        if not has_open_round:
            return {
                "draft": "done",
                "start_review": "active",
                "audit_references": "pending",
                "resolve_comments": "pending",
                "close_round": "pending",
                "approved": "pending",
            }
        if pending_refs > 0:
            return {
                "draft": "done",
                "start_review": "done",
                "audit_references": "blocked",
                "resolve_comments": "pending",
                "close_round": "pending",
                "approved": "pending",
            }
        if open_comments > 0:
            return {
                "draft": "done",
                "start_review": "done",
                "audit_references": "done",
                "resolve_comments": "blocked",
                "close_round": "pending",
                "approved": "pending",
            }
        return {
            "draft": "done",
            "start_review": "done",
            "audit_references": "done",
            "resolve_comments": "done",
            "close_round": "active",
            "approved": "pending",
        }

    if version_status == "draft":
        statuses = {
            "draft": "active",
            "start_review": "pending",
            "audit_references": "pending",
            "resolve_comments": "pending",
            "close_round": "pending",
            "approved": "pending",
        }
        if has_latest_round and latest_round_outcome == "rejected":
            statuses["start_review"] = "done"
            statuses["close_round"] = "done"
        return statuses

    return {
        "draft": "pending",
        "start_review": "pending",
        "audit_references": "pending",
        "resolve_comments": "pending",
        "close_round": "pending",
        "approved": "pending",
    }


def _steps(statuses: dict[str, str], version, open_round, latest_round,
           ref_metrics: dict[str, int], comment_metrics: dict[str, int],
           blocking: bool) -> list[dict[str, Any]]:
    round_metrics = {
        "open_round_id": str(open_round["id"]) if open_round else None,
        "latest_round_id": str(latest_round["id"]) if latest_round else None,
        "latest_round_status": latest_round["status"] if latest_round else None,
        "latest_round_outcome": latest_round["outcome"] if latest_round else None,
    }
    return [
        _step(
            "draft", "起草版本", "standard_editor",
            statuses["draft"],
            "版本处于 draft 后可启动审定。",
            {"version_status": version["status"],
             "version_label": version["version_label"]},
        ),
        _step(
            "start_review", "启动审定", "admin",
            statuses["start_review"],
            "管理员指定 reviewer 并创建审定 round。",
            round_metrics,
        ),
        _step(
            "audit_references", "引用审定", "standard_reviewer",
            statuses["audit_references"],
            "Reviewer 逐条确认引用依据。",
            ref_metrics,
        ),
        _step(
            "resolve_comments", "意见处理", "standard_reviewer",
            statuses["resolve_comments"],
            "Reviewer 关闭或归类所有审定意见。",
            comment_metrics,
        ),
        _step(
            "close_round", "关闭审定", "standard_reviewer",
            statuses["close_round"],
            "通过时必须满足引用和评论门禁，驳回则返回 draft。",
            {**round_metrics, "blocking": blocking},
        ),
        _step(
            "approved", "审定通过", "admin",
            statuses["approved"],
            "版本进入 approved 后可进入发布环节。",
            {"version_status": version["status"]},
        ),
    ]


def _step(step_id: str, label: str, role: str, status: str,
          description: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": step_id,
        "label": label,
        "role": role,
        "status": status,
        "description": description,
        "metrics": metrics,
    }


def _edges() -> list[dict[str, str]]:
    pairs = [
        ("draft", "start_review", "admin starts round"),
        ("start_review", "audit_references", "reviewer audits references"),
        ("audit_references", "resolve_comments", "reviewer resolves comments"),
        ("resolve_comments", "close_round", "gates clear"),
        ("close_round", "approved", "approved outcome"),
    ]
    return [
        {"source": source, "target": target, "label": label}
        for source, target, label in pairs
    ]
