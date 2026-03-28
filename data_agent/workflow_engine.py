"""
Workflow Engine — Multi-step pipeline workflows with scheduling, webhook push, and SLA.

v5.4: Users create reusable workflows that chain pipeline executions,
run them manually or on a cron schedule, and push results via webhook.
v15.6: SLA/timeout per step, QC workflow templates, priority.
"""
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import text

from .db_engine import get_engine
from .user_context import current_user_id, current_session_id, current_user_role

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Table names
# ---------------------------------------------------------------------------

T_WORKFLOWS = "agent_workflows"
T_WORKFLOW_RUNS = "agent_workflow_runs"


# ---------------------------------------------------------------------------
# Table initialization
# ---------------------------------------------------------------------------

def ensure_workflow_tables():
    """Create workflow tables if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[Workflows] WARNING: Database not configured. Workflow system disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_WORKFLOWS} (
                    id SERIAL PRIMARY KEY,
                    workflow_name VARCHAR(200) NOT NULL,
                    description TEXT DEFAULT '',
                    owner_username VARCHAR(100) NOT NULL,
                    is_shared BOOLEAN DEFAULT FALSE,
                    pipeline_type VARCHAR(30) DEFAULT 'general',
                    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
                    parameters JSONB DEFAULT '{{}}'::jsonb,
                    graph_data JSONB DEFAULT '{{}}'::jsonb,
                    cron_schedule VARCHAR(100) DEFAULT NULL,
                    webhook_url TEXT DEFAULT NULL,
                    use_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(owner_username, workflow_name)
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_workflows_owner "
                f"ON {T_WORKFLOWS} (owner_username)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_workflows_shared "
                f"ON {T_WORKFLOWS} (is_shared, created_at DESC)"
            ))
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_WORKFLOW_RUNS} (
                    id SERIAL PRIMARY KEY,
                    workflow_id INT REFERENCES {T_WORKFLOWS}(id) ON DELETE CASCADE,
                    run_by VARCHAR(100) NOT NULL,
                    status VARCHAR(20) DEFAULT 'running',
                    parameters_used JSONB DEFAULT '{{}}'::jsonb,
                    step_results JSONB DEFAULT '[]'::jsonb,
                    total_duration FLOAT DEFAULT 0,
                    total_input_tokens INT DEFAULT 0,
                    total_output_tokens INT DEFAULT 0,
                    error_message TEXT DEFAULT NULL,
                    webhook_sent BOOLEAN DEFAULT FALSE,
                    started_at TIMESTAMP DEFAULT NOW(),
                    completed_at TIMESTAMP DEFAULT NULL
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_workflow_runs_wf "
                f"ON {T_WORKFLOW_RUNS} (workflow_id, started_at DESC)"
            ))
            # v14.0: checkpoint column
            conn.execute(text(
                f"ALTER TABLE {T_WORKFLOW_RUNS} "
                f"ADD COLUMN IF NOT EXISTS node_checkpoints JSONB DEFAULT '{{}}'::jsonb"
            ))
            # v15.6: SLA and priority columns
            conn.execute(text(
                f"ALTER TABLE {T_WORKFLOWS} "
                f"ADD COLUMN IF NOT EXISTS sla_total_seconds INTEGER"
            ))
            conn.execute(text(
                f"ALTER TABLE {T_WORKFLOWS} "
                f"ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal'"
            ))
            conn.execute(text(
                f"ALTER TABLE {T_WORKFLOWS} "
                f"ADD COLUMN IF NOT EXISTS template_source VARCHAR(100)"
            ))
            conn.execute(text(
                f"ALTER TABLE {T_WORKFLOW_RUNS} "
                f"ADD COLUMN IF NOT EXISTS sla_violated BOOLEAN DEFAULT FALSE"
            ))
            conn.execute(text(
                f"ALTER TABLE {T_WORKFLOW_RUNS} "
                f"ADD COLUMN IF NOT EXISTS timeout_steps JSONB DEFAULT '[]'::jsonb"
            ))
            conn.commit()
            print("[Workflows] Tables ready.")
    except Exception as e:
        print(f"[Workflows] WARNING: Table creation failed: {e}")


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def create_workflow(
    name: str,
    description: str = "",
    steps: list = None,
    parameters: dict = None,
    graph_data: dict = None,
    cron_schedule: str = None,
    webhook_url: str = None,
    pipeline_type: str = "general",
) -> Optional[int]:
    """Create a new workflow. Returns workflow ID or None."""
    engine = get_engine()
    if not engine:
        return None

    user = current_user_id.get()
    if not user:
        return None

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                INSERT INTO {T_WORKFLOWS}
                    (workflow_name, description, owner_username, pipeline_type,
                     steps, parameters, graph_data, cron_schedule, webhook_url)
                VALUES (:name, :desc, :owner, :ptype,
                        :steps, :params, :graph,
                        :cron, :webhook)
                RETURNING id
            """), {
                "name": name,
                "desc": description,
                "owner": user,
                "ptype": pipeline_type,
                "steps": json.dumps(steps or []),
                "params": json.dumps(parameters or {}),
                "graph": json.dumps(graph_data or {}),
                "cron": cron_schedule,
                "webhook": webhook_url,
            })
            row = result.fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception as e:
        print(f"[Workflows] Create failed: {e}")
        return None


def get_workflow(workflow_id: int) -> Optional[dict]:
    """Get workflow by ID. Returns dict or None."""
    engine = get_engine()
    if not engine:
        return None

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT id, workflow_name, description, owner_username, is_shared,
                       pipeline_type, steps, parameters, graph_data,
                       cron_schedule, webhook_url, use_count,
                       created_at, updated_at
                FROM {T_WORKFLOWS}
                WHERE id = :id
            """), {"id": workflow_id})
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "workflow_name": row[1],
                "description": row[2],
                "owner_username": row[3],
                "is_shared": row[4],
                "pipeline_type": row[5],
                "steps": row[6] if isinstance(row[6], list) else json.loads(row[6] or "[]"),
                "parameters": row[7] if isinstance(row[7], dict) else json.loads(row[7] or "{}"),
                "graph_data": row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}"),
                "cron_schedule": row[9],
                "webhook_url": row[10],
                "use_count": row[11],
                "created_at": str(row[12]) if row[12] else None,
                "updated_at": str(row[13]) if row[13] else None,
            }
    except Exception as e:
        print(f"[Workflows] Get failed: {e}")
        return None


def list_workflows(keyword: str = "") -> list:
    """List workflows visible to current user (own + shared)."""
    engine = get_engine()
    if not engine:
        return []

    user = current_user_id.get() or ""
    try:
        with engine.connect() as conn:
            if keyword:
                result = conn.execute(text(f"""
                    SELECT id, workflow_name, description, owner_username, is_shared,
                           pipeline_type, cron_schedule, use_count, created_at
                    FROM {T_WORKFLOWS}
                    WHERE (owner_username = :user OR is_shared = TRUE)
                      AND (workflow_name ILIKE :kw OR description ILIKE :kw)
                    ORDER BY updated_at DESC
                """), {"user": user, "kw": f"%{keyword}%"})
            else:
                result = conn.execute(text(f"""
                    SELECT id, workflow_name, description, owner_username, is_shared,
                           pipeline_type, cron_schedule, use_count, created_at
                    FROM {T_WORKFLOWS}
                    WHERE owner_username = :user OR is_shared = TRUE
                    ORDER BY updated_at DESC
                """), {"user": user})

            rows = result.fetchall()
            return [{
                "id": r[0],
                "workflow_name": r[1],
                "description": r[2],
                "owner_username": r[3],
                "is_shared": r[4],
                "pipeline_type": r[5],
                "cron_schedule": r[6],
                "use_count": r[7],
                "created_at": str(r[8]) if r[8] else None,
            } for r in rows]
    except Exception as e:
        print(f"[Workflows] List failed: {e}")
        return []


def update_workflow(workflow_id: int, **updates) -> bool:
    """Update workflow fields. Only owner can update."""
    engine = get_engine()
    if not engine:
        return False

    user = current_user_id.get()
    if not user:
        return False

    allowed = {
        "workflow_name", "description", "steps", "parameters", "graph_data",
        "cron_schedule", "webhook_url", "pipeline_type", "is_shared",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return False

    set_clauses = []
    params = {"id": workflow_id, "owner": user}
    for k, v in filtered.items():
        if k in ("steps", "parameters", "graph_data"):
            set_clauses.append(f"{k} = :{k}")
            params[k] = json.dumps(v) if not isinstance(v, str) else v
        else:
            set_clauses.append(f"{k} = :{k}")
            params[k] = v
    set_clauses.append("updated_at = NOW()")

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                UPDATE {T_WORKFLOWS}
                SET {', '.join(set_clauses)}
                WHERE id = :id AND owner_username = :owner
            """), params)
            conn.commit()
            return result.rowcount > 0
    except Exception as e:
        print(f"[Workflows] Update failed: {e}")
        return False


def delete_workflow(workflow_id: int) -> bool:
    """Delete workflow. Only owner can delete."""
    engine = get_engine()
    if not engine:
        return False

    user = current_user_id.get()
    if not user:
        return False

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                DELETE FROM {T_WORKFLOWS}
                WHERE id = :id AND owner_username = :owner
            """), {"id": workflow_id, "owner": user})
            conn.commit()
            return result.rowcount > 0
    except Exception as e:
        print(f"[Workflows] Delete failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _substitute_params(text_val: str, params: dict) -> str:
    """Replace {param_name} placeholders in text with parameter values."""
    for key, value in params.items():
        text_val = text_val.replace(f"{{{key}}}", str(value))
    return text_val


async def execute_workflow(
    workflow_id: int,
    param_overrides: dict = None,
    run_by: str = None,
    progress_callback=None,
) -> dict:
    """Execute a workflow: run each step sequentially via pipeline_runner.

    Args:
        progress_callback: Optional async callable(dict) invoked after each step
            with keys: step_idx, step_id, step_label, status, duration, summary, error.

    Returns dict with run_id, status, step_results, duration, tokens.
    """
    from .pipeline_runner import run_pipeline_headless
    from google.adk.sessions import InMemorySessionService

    workflow = get_workflow(workflow_id)
    if not workflow:
        return {"status": "failed", "error": "Workflow not found"}

    user = run_by or current_user_id.get() or workflow["owner_username"]
    steps = workflow.get("steps", [])
    if not steps:
        return {"status": "failed", "error": "Workflow has no steps"}

    # Merge parameters: defaults + overrides
    params = {}
    for k, v in workflow.get("parameters", {}).items():
        params[k] = v.get("default", "") if isinstance(v, dict) else v
    if param_overrides:
        params.update(param_overrides)

    # Create run record
    engine = get_engine()
    run_id = None
    if engine:
        try:
            with engine.connect() as conn:
                result = conn.execute(text(f"""
                    INSERT INTO {T_WORKFLOW_RUNS}
                        (workflow_id, run_by, status, parameters_used)
                    VALUES (:wf_id, :user, 'running', :params)
                    RETURNING id
                """), {
                    "wf_id": workflow_id,
                    "user": user,
                    "params": json.dumps(params),
                })
                row = result.fetchone()
                run_id = row[0] if row else None
                conn.commit()
        except Exception as e:
            print(f"[Workflows] Run record creation failed: {e}")

    # Import agents lazily to avoid circular imports
    from . import agent as agent_module

    session_service = InMemorySessionService()
    session_id = f"wf_{workflow_id}_{uuid.uuid4().hex[:8]}"

    # Set user context
    current_user_id.set(user)
    current_session_id.set(session_id)
    current_user_role.set("analyst")

    start_time = time.time()
    step_results = []
    total_input = 0
    total_output = 0
    error_msg = None
    status = "completed"
    timeout_steps = []
    sla_total = workflow.get("sla_total_seconds")
    accumulated_context = ""  # Context from previous steps

    for i, step in enumerate(steps):
        step_id = step.get("step_id", f"step_{i}")
        pipeline_type = step.get("pipeline_type", "general")
        base_prompt = _substitute_params(step.get("prompt", ""), params)

        # Inject previous step context
        if accumulated_context:
            prompt = f"{base_prompt}\n\n[上一步结果]\n{accumulated_context}"
        else:
            prompt = base_prompt

        intent = pipeline_type.upper()
        sla_seconds = step.get("sla_seconds")
        retry_on_timeout = step.get("retry_on_timeout", False)
        max_retries = step.get("max_retries", 0)

        # Notify progress callback: step starting
        if progress_callback:
            try:
                await progress_callback({
                    "step_idx": i,
                    "step_id": step_id,
                    "step_label": step.get("label", step_id),
                    "status": "running",
                    "total_steps": len(steps),
                })
            except Exception:
                pass

        # Select agent
        agent_obj = _get_agent_for_pipeline(agent_module, pipeline_type, step)
        if not agent_obj:
            error_msg = f"Unknown pipeline_type: {pipeline_type}"
            status = "failed"
            break

        attempt = 0
        step_done = False
        while not step_done:
            try:
                coro = run_pipeline_headless(
                    agent=agent_obj,
                    session_service=session_service,
                    user_id=user,
                    session_id=f"{session_id}_{step_id}_{attempt}",
                    prompt=prompt,
                    pipeline_type=pipeline_type,
                    intent=intent,
                    role="analyst",
                )
                # Apply SLA timeout if configured
                if sla_seconds and sla_seconds > 0:
                    result = await asyncio.wait_for(coro, timeout=sla_seconds)
                else:
                    result = await coro

                step_results.append({
                    "step_id": step_id,
                    "label": step.get("label", step_id),
                    "status": "failed" if result.error else "completed",
                    "duration": result.duration_seconds,
                    "input_tokens": result.total_input_tokens,
                    "output_tokens": result.total_output_tokens,
                    "files": result.generated_files,
                    "error": result.error,
                    "summary": (result.report_text or "")[:500],
                    "attempt": attempt + 1,
                })
                total_input += result.total_input_tokens
                total_output += result.total_output_tokens

                # Extract key context for next step
                if not result.error and result.report_text:
                    summary = result.report_text[:800]  # Keep last 800 chars
                    file_info = ""
                    if result.generated_files:
                        file_info = f"\n生成文件: {', '.join(result.generated_files[:3])}"
                    accumulated_context = f"步骤 {i+1} ({step.get('label', step_id)}):\n{summary}{file_info}"

                # Notify progress callback
                if progress_callback:
                    try:
                        await progress_callback({
                            "step_idx": i,
                            "step_id": step_id,
                            "step_label": step.get("label", step_id),
                            "status": "failed" if result.error else "completed",
                            "duration": result.duration_seconds,
                            "summary": (result.report_text or "")[:200],
                            "error": result.error,
                            "total_steps": len(steps),
                        })
                    except Exception as cb_err:
                        print(f"[Workflows] Progress callback error: {cb_err}")

                if result.error:
                    error_msg = f"Step '{step_id}' failed: {result.error}"
                    status = "failed"
                step_done = True

            except asyncio.TimeoutError:
                timeout_steps.append({
                    "step_id": step_id,
                    "attempt": attempt + 1,
                    "sla_seconds": sla_seconds,
                    "timestamp": datetime.now().isoformat(),
                })
                logger.warning("Step '%s' timed out (SLA: %ds, attempt %d)", step_id, sla_seconds, attempt + 1)
                if retry_on_timeout and attempt < max_retries:
                    attempt += 1
                    continue
                step_results.append({
                    "step_id": step_id,
                    "label": step.get("label", step_id),
                    "status": "timeout",
                    "error": f"SLA timeout ({sla_seconds}s) after {attempt + 1} attempt(s)",
                    "attempt": attempt + 1,
                })
                error_msg = f"Step '{step_id}' timed out"
                status = "failed"
                step_done = True

            except Exception as e:
                error_msg = f"Step '{step_id}' exception: {str(e)}"
                status = "failed"
                step_results.append({
                    "step_id": step_id,
                    "label": step.get("label", step_id),
                    "status": "failed",
                    "error": str(e),
                })
                step_done = True

        if status == "failed":
            break

    duration = time.time() - start_time

    # Check SLA violation
    sla_violated = bool(timeout_steps) or (sla_total and duration > sla_total)

    # Update run record
    webhook_sent = False
    if engine and run_id:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    UPDATE {T_WORKFLOW_RUNS}
                    SET status = :status, step_results = :results,
                        total_duration = :dur, total_input_tokens = :inp,
                        total_output_tokens = :out, error_message = :err,
                        sla_violated = :sla_v, timeout_steps = :ts,
                        completed_at = NOW()
                    WHERE id = :id
                """), {
                    "id": run_id,
                    "status": status,
                    "results": json.dumps(step_results),
                    "dur": duration,
                    "inp": total_input,
                    "out": total_output,
                    "err": error_msg,
                    "sla_v": sla_violated,
                    "ts": json.dumps(timeout_steps),
                })
                # Increment use_count
                conn.execute(text(f"""
                    UPDATE {T_WORKFLOWS}
                    SET use_count = use_count + 1, updated_at = NOW()
                    WHERE id = :wf_id
                """), {"wf_id": workflow_id})
                conn.commit()
        except Exception as e:
            print(f"[Workflows] Run record update failed: {e}")

    # Send webhook if configured
    if workflow.get("webhook_url"):
        payload = {
            "workflow_id": workflow_id,
            "workflow_name": workflow["workflow_name"],
            "run_id": run_id,
            "status": status,
            "duration": round(duration, 2),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "step_results": step_results,
            "error": error_msg,
            "timestamp": datetime.utcnow().isoformat(),
        }
        webhook_sent = await send_webhook(workflow["webhook_url"], payload)
        if engine and run_id:
            try:
                with engine.connect() as conn:
                    conn.execute(text(f"""
                        UPDATE {T_WORKFLOW_RUNS}
                        SET webhook_sent = :sent WHERE id = :id
                    """), {"sent": webhook_sent, "id": run_id})
                    conn.commit()
            except Exception:
                pass

    return {
        "run_id": run_id,
        "status": status,
        "step_results": step_results,
        "duration": round(duration, 2),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "error": error_msg,
        "webhook_sent": webhook_sent,
    }


def _get_agent_for_pipeline(agent_module, pipeline_type: str, step: dict = None):
    """Get the appropriate agent for a pipeline type.

    For 'custom_skill' type, dynamically builds an LlmAgent from the
    referenced skill in the database.
    """
    if pipeline_type == "custom_skill":
        skill_id = (step or {}).get("skill_id")
        if not skill_id:
            return None
        from .custom_skills import get_custom_skill, build_custom_agent
        skill = get_custom_skill(int(skill_id))
        if not skill:
            return None
        return build_custom_agent(skill)

    mapping = {
        "general": "general_pipeline",
        "governance": "governance_pipeline",
        "optimization": "data_pipeline",
        "planner": "planner_agent",
    }
    attr = mapping.get(pipeline_type)
    if attr:
        return getattr(agent_module, attr, None)
    return None


# ---------------------------------------------------------------------------
# Execution history
# ---------------------------------------------------------------------------

def get_workflow_runs(workflow_id: int, limit: int = 20) -> list:
    """Get recent runs for a workflow."""
    engine = get_engine()
    if not engine:
        return []

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT id, run_by, status, parameters_used, step_results,
                       total_duration, total_input_tokens, total_output_tokens,
                       error_message, webhook_sent, started_at, completed_at
                FROM {T_WORKFLOW_RUNS}
                WHERE workflow_id = :wf_id
                ORDER BY started_at DESC
                LIMIT :lim
            """), {"wf_id": workflow_id, "lim": limit})
            rows = result.fetchall()
            return [{
                "id": r[0],
                "run_by": r[1],
                "status": r[2],
                "parameters_used": r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}"),
                "step_results": r[4] if isinstance(r[4], list) else json.loads(r[4] or "[]"),
                "total_duration": r[5],
                "total_input_tokens": r[6],
                "total_output_tokens": r[7],
                "error_message": r[8],
                "webhook_sent": r[9],
                "started_at": str(r[10]) if r[10] else None,
                "completed_at": str(r[11]) if r[11] else None,
            } for r in rows]
    except Exception as e:
        print(f"[Workflows] Get runs failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

async def send_webhook(url: str, payload: dict) -> bool:
    """POST workflow result to webhook URL. Returns True on success."""
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            return 200 <= resp.status_code < 300
    except Exception as e:
        print(f"[Workflows] Webhook failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Scheduler (APScheduler)
# ---------------------------------------------------------------------------

class WorkflowScheduler:
    """Manages cron-based workflow execution using APScheduler."""

    def __init__(self):
        self._scheduler = None

    def start(self):
        """Start the background scheduler."""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            self._scheduler = AsyncIOScheduler()
            self._scheduler.start()
            self.sync_jobs()
            print("[Workflows] Scheduler started.")
        except ImportError:
            print("[Workflows] APScheduler not installed. Cron scheduling disabled.")
        except Exception as e:
            print(f"[Workflows] Scheduler start failed: {e}")

    def stop(self):
        """Shutdown the scheduler."""
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
                print("[Workflows] Scheduler stopped.")
            except Exception:
                pass

    def sync_jobs(self):
        """Load all workflows with cron_schedule from DB and register jobs."""
        if not self._scheduler:
            return

        engine = get_engine()
        if not engine:
            return

        try:
            # Remove existing workflow jobs
            for job in self._scheduler.get_jobs():
                if job.id.startswith("wf_cron_"):
                    job.remove()

            with engine.connect() as conn:
                result = conn.execute(text(f"""
                    SELECT id, cron_schedule, owner_username
                    FROM {T_WORKFLOWS}
                    WHERE cron_schedule IS NOT NULL AND cron_schedule != ''
                """))
                rows = result.fetchall()

            for row in rows:
                wf_id, cron_expr, owner = row[0], row[1], row[2]
                self._add_cron_job(wf_id, cron_expr, owner)

            print(f"[Workflows] Synced {len(rows)} cron jobs.")
        except Exception as e:
            print(f"[Workflows] Sync jobs failed: {e}")

    def _add_cron_job(self, workflow_id: int, cron_expr: str, owner: str):
        """Parse cron expression and add a job."""
        if not self._scheduler:
            return
        try:
            from apscheduler.triggers.cron import CronTrigger
            parts = cron_expr.strip().split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0], hour=parts[1],
                    day=parts[2], month=parts[3],
                    day_of_week=parts[4],
                )
            else:
                print(f"[Workflows] Invalid cron: '{cron_expr}' for workflow {workflow_id}")
                return

            self._scheduler.add_job(
                self._on_cron_trigger,
                trigger=trigger,
                args=[workflow_id, owner],
                id=f"wf_cron_{workflow_id}",
                replace_existing=True,
            )
        except Exception as e:
            print(f"[Workflows] Failed to add cron job for workflow {workflow_id}: {e}")

    def _on_cron_trigger(self, workflow_id: int, owner: str):
        """Called by APScheduler on cron trigger. Runs workflow in event loop."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    execute_workflow(workflow_id, run_by=owner)
                )
            else:
                loop.run_until_complete(
                    execute_workflow(workflow_id, run_by=owner)
                )
        except Exception as e:
            print(f"[Workflows] Cron execution failed for workflow {workflow_id}: {e}")


# ---------------------------------------------------------------------------
# DAG Execution Engine (v8.0.3)
# ---------------------------------------------------------------------------

import re as _re
from collections import deque

# In-memory live status for active DAG runs (cleaned up after completion + TTL)
_live_run_status: dict[int, dict] = {}
_LIVE_STATUS_MAX = 100  # Max entries to prevent unbounded growth


def _is_dag_workflow(steps: list) -> bool:
    """Return True if any step has a non-empty depends_on list."""
    return any(step.get("depends_on") for step in steps)


def _topological_sort(steps: list[dict]) -> list[list[dict]]:
    """Kahn's algorithm: sort DAG steps into parallel execution layers.

    Returns list of layers — each layer is a list of steps that can
    execute concurrently (all their dependencies are in earlier layers).

    Raises ValueError if the graph contains a cycle.
    """
    step_map = {s["step_id"]: s for s in steps}
    all_ids = set(step_map.keys())

    # Build in-degree and adjacency (reverse: parent → children)
    in_degree = {sid: 0 for sid in all_ids}
    children = {sid: [] for sid in all_ids}

    for step in steps:
        for dep in step.get("depends_on", []):
            if dep not in all_ids:
                # Gracefully ignore missing dependency
                continue
            in_degree[step["step_id"]] += 1
            children[dep].append(step["step_id"])

    # Seed with zero-in-degree nodes
    queue = deque(sid for sid, deg in in_degree.items() if deg == 0)
    layers = []
    visited = 0

    while queue:
        # Current layer: all nodes with in-degree 0
        layer = []
        next_queue = deque()
        while queue:
            sid = queue.popleft()
            layer.append(step_map[sid])
            visited += 1
            for child in children[sid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_queue.append(child)
        layers.append(layer)
        queue = next_queue

    if visited < len(all_ids):
        unvisited = all_ids - {s["step_id"] for layer in layers for s in layer}
        raise ValueError(
            f"Cycle detected in workflow DAG involving nodes: {sorted(unvisited)}"
        )

    return layers


def _evaluate_condition(expression: str, node_outputs: dict) -> bool:
    """Evaluate a condition expression with {step_id.field} substitution.

    Supported fields: output, error, status, files.
    Supported operators: ==, !=, and, or, None, True, False.
    Fail-open: returns True on any parse/eval error.
    """
    if not expression or not expression.strip():
        return True

    try:
        # Substitute {step_id.field} references
        def _replace(match):
            step_id = match.group(1)
            field_name = match.group(2)
            node = node_outputs.get(step_id, {})
            val = node.get(field_name)
            if val is None:
                return "None"
            if isinstance(val, bool):
                return str(val)
            if isinstance(val, (int, float)):
                return str(val)
            # String value — wrap in quotes
            safe_val = str(val).replace('"', '\\"')[:200]
            return f'"{safe_val}"'

        expr = _re.sub(r'\{(\w+)\.(output|error|status|files)\}', _replace, expression)

        # Restricted eval — only safe builtins
        safe_ns = {"__builtins__": {}, "None": None, "True": True, "False": False}
        result = eval(expr, safe_ns)  # noqa: S307
        return bool(result)
    except Exception:
        # Fail-open: condition parse error → downstream still runs
        return True


def _substitute_params_dag(
    text_val: str, params: dict, node_outputs: dict
) -> str:
    """Enhanced parameter substitution with inter-node data references.

    Standard {param_name} replacement PLUS:
    - {step_id.output} → upstream report_text (truncated to 2000 chars)
    - {step_id.files}  → comma-separated list of generated file paths
    - {step_id.error}  → error string or empty
    """
    # Standard param substitution first
    for key, value in params.items():
        text_val = text_val.replace(f"{{{key}}}", str(value))

    # Node output substitution
    def _replace_node_ref(match):
        step_id = match.group(1)
        field_name = match.group(2)
        node = node_outputs.get(step_id, {})
        if field_name == "output":
            val = node.get("report_text", "")
            return str(val)[:2000] if val else ""
        elif field_name == "files":
            files = node.get("files", [])
            return ", ".join(str(f) for f in files) if files else ""
        elif field_name == "error":
            return str(node.get("error", "")) or ""
        elif field_name == "status":
            return str(node.get("status", "unknown"))
        return match.group(0)

    text_val = _re.sub(
        r'\{(\w+)\.(output|files|error|status)\}', _replace_node_ref, text_val
    )

    return text_val


def _update_live_status(
    run_id: int, step_id: str, status: str, result_data: dict = None
):
    """Update in-memory per-node status for live polling."""
    if run_id not in _live_run_status:
        _live_run_status[run_id] = {"nodes": {}, "status": "running"}

    node = _live_run_status[run_id]["nodes"].setdefault(step_id, {})
    node["status"] = status

    now = datetime.utcnow().isoformat()
    if status == "running":
        node["started_at"] = now
    elif status in ("completed", "failed", "skipped"):
        node["completed_at"] = now

    if result_data:
        node.update({
            k: result_data[k]
            for k in ("duration", "error", "summary", "files")
            if k in result_data
        })

    # FIFO eviction if too many entries
    if len(_live_run_status) > _LIVE_STATUS_MAX:
        oldest_key = next(iter(_live_run_status))
        _live_run_status.pop(oldest_key, None)


def get_live_run_status(run_id: int) -> dict | None:
    """Get live per-node execution status for an active DAG run.

    Returns None if run_id not found (already cleaned up or never existed).
    """
    return _live_run_status.get(run_id)


async def execute_workflow_dag(
    workflow_id: int,
    param_overrides: dict = None,
    run_by: str = None,
) -> dict:
    """Execute a DAG workflow: honor depends_on, parallel layers, failure isolation.

    Compatible return format with execute_workflow().
    """
    from .pipeline_runner import run_pipeline_headless
    from google.adk.sessions import InMemorySessionService

    workflow = get_workflow(workflow_id)
    if not workflow:
        return {"status": "failed", "error": "Workflow not found"}

    user = run_by or current_user_id.get() or workflow["owner_username"]
    steps = workflow.get("steps", [])
    if not steps:
        return {"status": "failed", "error": "Workflow has no steps"}

    # Merge parameters
    params = {}
    for k, v in workflow.get("parameters", {}).items():
        params[k] = v.get("default", "") if isinstance(v, dict) else v
    if param_overrides:
        params.update(param_overrides)

    # Create run record
    engine = get_engine()
    run_id = None
    if engine:
        try:
            with engine.connect() as conn:
                result = conn.execute(text(f"""
                    INSERT INTO {T_WORKFLOW_RUNS}
                        (workflow_id, run_by, status, parameters_used)
                    VALUES (:wf_id, :user, 'running', :params)
                    RETURNING id
                """), {
                    "wf_id": workflow_id,
                    "user": user,
                    "params": json.dumps(params),
                })
                row = result.fetchone()
                run_id = row[0] if row else None
                conn.commit()
        except Exception as e:
            print(f"[DAG] Run record creation failed: {e}")

    # Import agents lazily
    from . import agent as agent_module

    session_service = InMemorySessionService()
    session_id = f"dag_{workflow_id}_{uuid.uuid4().hex[:8]}"

    # Set user context
    current_user_id.set(user)
    current_session_id.set(session_id)
    current_user_role.set("analyst")

    start_time = time.time()
    step_results = []
    node_outputs = {}  # step_id → {report_text, files, error, status}
    failed_or_skipped = set()
    total_input = 0
    total_output = 0
    error_msg = None
    overall_status = "completed"

    # Topological sort
    try:
        layers = _topological_sort(steps)
    except ValueError as e:
        overall_status = "failed"
        error_msg = str(e)
        # Update DB
        if engine and run_id:
            try:
                with engine.connect() as conn:
                    conn.execute(text(f"""
                        UPDATE {T_WORKFLOW_RUNS}
                        SET status = 'failed', error_message = :err, completed_at = NOW()
                        WHERE id = :id
                    """), {"id": run_id, "err": error_msg})
                    conn.commit()
            except Exception:
                pass
        return {
            "run_id": run_id, "status": "failed", "step_results": [],
            "duration": 0, "total_input_tokens": 0, "total_output_tokens": 0,
            "error": error_msg, "webhook_sent": False,
        }

    # Initialize live status
    if run_id:
        _live_run_status[run_id] = {"workflow_id": workflow_id, "status": "running", "nodes": {}}
        for step in steps:
            _update_live_status(run_id, step["step_id"], "pending")

    # Execute layer by layer
    for layer in layers:
        async def _run_node(step):
            """Execute a single DAG node. Returns (step_id, result_dict)."""
            step_id = step["step_id"]
            label = step.get("label", step_id)

            # Check upstream dependencies
            for dep in step.get("depends_on", []):
                if dep in failed_or_skipped:
                    reason = f"Upstream '{dep}' failed or was skipped"
                    if run_id:
                        _update_live_status(run_id, step_id, "skipped", {"error": reason})
                    return (step_id, {
                        "step_id": step_id, "label": label,
                        "status": "skipped", "error": reason,
                        "depends_on": step.get("depends_on", []),
                    })

            # Condition node — evaluate expression, don't run pipeline
            if step.get("pipeline_type") == "condition":
                condition_expr = step.get("condition", step.get("prompt", ""))
                result_bool = _evaluate_condition(condition_expr, node_outputs)
                status_val = "completed"
                if run_id:
                    _update_live_status(run_id, step_id, status_val)
                return (step_id, {
                    "step_id": step_id, "label": label,
                    "status": status_val,
                    "condition_result": result_bool,
                    "depends_on": step.get("depends_on", []),
                })

            # Pipeline node — run via headless runner
            pipeline_type = step.get("pipeline_type", "general")
            prompt = _substitute_params_dag(step.get("prompt", ""), params, node_outputs)

            agent_obj = _get_agent_for_pipeline(agent_module, pipeline_type, step)
            if not agent_obj:
                err = f"Unknown pipeline_type: {pipeline_type}"
                if run_id:
                    _update_live_status(run_id, step_id, "failed", {"error": err})
                return (step_id, {
                    "step_id": step_id, "label": label,
                    "status": "failed", "error": err,
                    "depends_on": step.get("depends_on", []),
                })

            if run_id:
                _update_live_status(run_id, step_id, "running")

            try:
                result = await run_pipeline_headless(
                    agent=agent_obj,
                    session_service=session_service,
                    user_id=user,
                    session_id=f"{session_id}_{step_id}",
                    prompt=prompt,
                    pipeline_type=pipeline_type,
                    intent=pipeline_type.upper(),
                    role="analyst",
                )
                node_status = "failed" if result.error else "completed"
                result_data = {
                    "step_id": step_id, "label": label,
                    "status": node_status,
                    "duration": result.duration_seconds,
                    "input_tokens": result.total_input_tokens,
                    "output_tokens": result.total_output_tokens,
                    "files": result.generated_files,
                    "error": result.error,
                    "summary": (result.report_text or "")[:500],
                    "report_text": result.report_text,
                    "depends_on": step.get("depends_on", []),
                }
                if run_id:
                    _update_live_status(run_id, step_id, node_status, result_data)
                return (step_id, result_data)
            except Exception as e:
                err_data = {
                    "step_id": step_id, "label": label,
                    "status": "failed", "error": str(e),
                    "depends_on": step.get("depends_on", []),
                }
                if run_id:
                    _update_live_status(run_id, step_id, "failed", err_data)
                return (step_id, err_data)

        # Run all nodes in this layer concurrently
        tasks = [_run_node(step) for step in layer]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for item in results:
            if isinstance(item, Exception):
                overall_status = "failed"
                error_msg = str(item)
                continue

            step_id, result_data = item

            # Store in node_outputs for downstream reference
            node_outputs[step_id] = result_data

            # Strip internal report_text from step_results (too verbose for DB)
            step_result = {k: v for k, v in result_data.items() if k != "report_text"}
            step_results.append(step_result)

            if result_data.get("status") == "failed":
                failed_or_skipped.add(step_id)
                if not error_msg:
                    error_msg = f"Node '{step_id}' failed: {result_data.get('error', 'unknown')}"
                overall_status = "failed"
            elif result_data.get("status") == "skipped":
                failed_or_skipped.add(step_id)

            # Condition node with False result → mark as skip-source for dependents
            if result_data.get("condition_result") is False:
                failed_or_skipped.add(step_id)

            total_input += result_data.get("input_tokens", 0)
            total_output += result_data.get("output_tokens", 0)

        # v14.0: Save checkpoint after each layer
        if engine and run_id:
            _save_checkpoint(engine, run_id, node_outputs, step_results)

    duration = time.time() - start_time

    # Update run record
    webhook_sent = False
    if engine and run_id:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    UPDATE {T_WORKFLOW_RUNS}
                    SET status = :status, step_results = :results,
                        total_duration = :dur, total_input_tokens = :inp,
                        total_output_tokens = :out, error_message = :err,
                        completed_at = NOW()
                    WHERE id = :id
                """), {
                    "id": run_id, "status": overall_status,
                    "results": json.dumps(step_results),
                    "dur": duration, "inp": total_input,
                    "out": total_output, "err": error_msg,
                })
                conn.execute(text(f"""
                    UPDATE {T_WORKFLOWS}
                    SET use_count = use_count + 1, updated_at = NOW()
                    WHERE id = :wf_id
                """), {"wf_id": workflow_id})
                conn.commit()
        except Exception as e:
            print(f"[DAG] Run record update failed: {e}")

    # Send webhook
    if workflow.get("webhook_url"):
        payload = {
            "workflow_id": workflow_id,
            "workflow_name": workflow["workflow_name"],
            "run_id": run_id,
            "status": overall_status,
            "duration": round(duration, 2),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "step_results": step_results,
            "error": error_msg,
            "timestamp": datetime.utcnow().isoformat(),
        }
        webhook_sent = await send_webhook(workflow["webhook_url"], payload)

    # Update live status to completed, schedule cleanup
    if run_id and run_id in _live_run_status:
        _live_run_status[run_id]["status"] = overall_status
        # Schedule cleanup after 5 minutes
        try:
            loop = asyncio.get_running_loop()
            loop.call_later(300, lambda: _live_run_status.pop(run_id, None))
        except Exception:
            _live_run_status.pop(run_id, None)

    return {
        "run_id": run_id,
        "status": overall_status,
        "step_results": step_results,
        "duration": round(duration, 2),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "error": error_msg,
        "webhook_sent": webhook_sent,
    }


# ---------------------------------------------------------------------------
# Checkpoint helpers (v14.0)
# ---------------------------------------------------------------------------

def _save_checkpoint(engine, run_id: int, node_outputs: dict, step_results: list):
    """Persist node_outputs to DB as checkpoint for resume capability."""
    try:
        # Serialize node_outputs (strip non-serializable fields)
        safe_outputs = {}
        for k, v in node_outputs.items():
            if isinstance(v, dict):
                safe_outputs[k] = {
                    kk: vv for kk, vv in v.items()
                    if isinstance(vv, (str, int, float, bool, list, dict, type(None)))
                }
            else:
                safe_outputs[k] = str(v)
        with engine.connect() as conn:
            conn.execute(text(
                f"UPDATE {T_WORKFLOW_RUNS} SET node_checkpoints = :cp, "
                f"step_results = :sr WHERE id = :id"
            ), {
                "id": run_id,
                "cp": json.dumps(safe_outputs, ensure_ascii=False, default=str),
                "sr": json.dumps(step_results, ensure_ascii=False, default=str),
            })
            conn.commit()
    except Exception as e:
        logger.debug("Checkpoint save failed for run %s: %s", run_id, e)


def get_run_checkpoint(run_id: int) -> dict | None:
    """Load checkpoint data for a workflow run."""
    engine = get_engine()
    if not engine:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT status, step_results, node_checkpoints, workflow_id "
                f"FROM {T_WORKFLOW_RUNS} WHERE id = :id"
            ), {"id": run_id}).fetchone()
        if not row:
            return None
        sr = row[1] if isinstance(row[1], list) else json.loads(row[1] or "[]")
        cp = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
        return {
            "status": row[0],
            "step_results": sr,
            "node_checkpoints": cp,
            "workflow_id": row[3],
        }
    except Exception:
        return None


async def retry_workflow_node(run_id: int, step_id: str, username: str) -> dict:
    """Retry a single failed node in a DAG workflow run.

    Loads the checkpoint, re-executes the specified node, and updates results.
    """
    checkpoint = get_run_checkpoint(run_id)
    if not checkpoint:
        return {"status": "error", "message": f"Run {run_id} not found"}
    if checkpoint["status"] not in ("failed", "completed"):
        return {"status": "error", "message": "Can only retry nodes in failed/completed runs"}

    workflow_id = checkpoint["workflow_id"]
    workflow = get_workflow(workflow_id, username)
    if not workflow:
        return {"status": "error", "message": "Workflow not found"}

    steps = workflow.get("steps", [])
    target_step = None
    for s in steps:
        if s.get("step_id") == step_id or s.get("name") == step_id:
            target_step = s
            break
    if not target_step:
        return {"status": "error", "message": f"Step '{step_id}' not found in workflow"}

    # Re-execute just this node
    node_outputs = checkpoint.get("node_checkpoints", {})
    params = workflow.get("parameters", {})

    from .pipeline_runner import run_pipeline_headless
    from .agent import general_pipeline
    from google.adk.sessions import InMemorySessionService

    prompt = _substitute_params_dag(
        target_step.get("prompt", ""), params, node_outputs
    )
    pipeline_type = target_step.get("pipeline_type", "general")

    try:
        session_svc = InMemorySessionService()
        session_id = f"retry_{run_id}_{step_id}"
        result = await run_pipeline_headless(
            agent=general_pipeline,
            session_service=session_svc,
            user_id=username,
            session_id=session_id,
            prompt=prompt,
            pipeline_type=pipeline_type,
        )
        result_data = {
            "step_id": step_id,
            "status": "completed" if not result.error else "failed",
            "files": result.generated_files,
            "input_tokens": result.total_input_tokens,
            "output_tokens": result.total_output_tokens,
            "duration": round(result.duration_seconds, 2),
            "error": result.error,
        }

        # Update checkpoint
        node_outputs[step_id] = result_data
        step_results = checkpoint.get("step_results", [])
        # Replace the old result for this step
        step_results = [sr for sr in step_results if sr.get("step_id") != step_id]
        step_results.append(result_data)

        engine = get_engine()
        if engine:
            new_status = "completed" if not result.error else "failed"
            _save_checkpoint(engine, run_id, node_outputs, step_results)
            try:
                with engine.connect() as conn:
                    conn.execute(text(
                        f"UPDATE {T_WORKFLOW_RUNS} SET status = :s WHERE id = :id"
                    ), {"s": new_status, "id": run_id})
                    conn.commit()
            except Exception:
                pass

        return {"status": "ok", "node": step_id, "result": result_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def resume_workflow_dag(run_id: int, username: str) -> dict:
    """Resume a failed/paused DAG workflow run from the last checkpoint.

    Loads the checkpoint, identifies incomplete nodes, and re-executes the
    remaining DAG layers from where execution stopped.
    """
    checkpoint = get_run_checkpoint(run_id)
    if not checkpoint:
        return {"status": "error", "message": f"Run {run_id} not found"}
    if checkpoint["status"] not in ("failed", "paused"):
        return {"status": "error", "message": f"Cannot resume run with status '{checkpoint['status']}'"}

    workflow_id = checkpoint["workflow_id"]
    workflow = get_workflow(workflow_id, username)
    if not workflow:
        return {"status": "error", "message": "Workflow not found"}

    node_outputs = checkpoint.get("node_checkpoints", {})
    completed_nodes = {k for k, v in node_outputs.items()
                       if isinstance(v, dict) and v.get("status") == "completed"}

    steps = workflow.get("steps", [])
    remaining_steps = [s for s in steps
                       if s.get("step_id", s.get("name", "")) not in completed_nodes]

    if not remaining_steps:
        return {"status": "ok", "message": "所有节点已完成，无需恢复", "completed": len(completed_nodes)}

    # Mark as running
    engine = get_engine()
    if engine:
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    f"UPDATE {T_WORKFLOW_RUNS} SET status = 'running' WHERE id = :id"
                ), {"id": run_id})
                conn.commit()
        except Exception:
            pass

    # Re-execute remaining nodes sequentially
    params = workflow.get("parameters", {})
    from .pipeline_runner import run_pipeline_headless
    from .agent import general_pipeline
    from google.adk.sessions import InMemorySessionService

    new_results = []
    final_error = None
    for step in remaining_steps:
        step_id = step.get("step_id", step.get("name", ""))
        prompt = _substitute_params_dag(step.get("prompt", ""), params, node_outputs)
        pipeline_type = step.get("pipeline_type", "general")
        try:
            session_svc = InMemorySessionService()
            result = await run_pipeline_headless(
                agent=general_pipeline, session_service=session_svc,
                user_id=username, session_id=f"resume_{run_id}_{step_id}",
                prompt=prompt, pipeline_type=pipeline_type,
            )
            result_data = {
                "step_id": step_id, "status": "completed" if not result.error else "failed",
                "files": result.generated_files,
                "duration": round(result.duration_seconds, 2),
                "error": result.error,
            }
            node_outputs[step_id] = result_data
            new_results.append(result_data)
            if result.error:
                final_error = result.error
                break
        except Exception as e:
            node_outputs[step_id] = {"step_id": step_id, "status": "failed", "error": str(e)}
            new_results.append(node_outputs[step_id])
            final_error = str(e)
            break

    # Update checkpoint
    all_results = checkpoint.get("step_results", []) + new_results
    if engine:
        _save_checkpoint(engine, run_id, node_outputs, all_results)
        new_status = "completed" if not final_error else "failed"
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    f"UPDATE {T_WORKFLOW_RUNS} SET status = :s WHERE id = :id"
                ), {"s": new_status, "id": run_id})
                conn.commit()
        except Exception:
            pass

    return {
        "status": "ok",
        "resumed_nodes": len(new_results),
        "completed_total": len([n for n in node_outputs.values()
                                if isinstance(n, dict) and n.get("status") == "completed"]),
        "final_status": "completed" if not final_error else "failed",
        "error": final_error,
    }


# ---------------------------------------------------------------------------
# Crash Recovery (v14.2)
# ---------------------------------------------------------------------------

def find_incomplete_runs(max_age_hours: int = 24) -> list[dict]:
    """Find workflow runs stuck in 'running' state (likely from process crash)."""
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT id, workflow_id, run_by, status, started_at "
                f"FROM {T_WORKFLOW_RUNS} "
                f"WHERE status = 'running' AND started_at < NOW() - INTERVAL ':h hours'"
            ), {"h": max_age_hours}).fetchall()
        return [
            {"run_id": r[0], "workflow_id": r[1], "run_by": r[2],
             "status": r[3], "started_at": str(r[4])}
            for r in rows
        ]
    except Exception:
        return []


def mark_run_failed(run_id: int, error_message: str = "Process crashed — marked as failed"):
    """Mark a stuck run as failed so it can be retried."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(
                f"UPDATE {T_WORKFLOW_RUNS} SET status = 'failed', "
                f"error_message = :err, completed_at = NOW() WHERE id = :id"
            ), {"id": run_id, "err": error_message})
            conn.commit()
    except Exception:
        pass


def recover_incomplete_runs():
    """Scan for and mark crashed runs on startup. Returns count recovered."""
    incomplete = find_incomplete_runs(max_age_hours=1)
    count = 0
    for run in incomplete:
        mark_run_failed(run["run_id"])
        logger.info("Recovered crashed workflow run %d (workflow=%d, user=%s)",
                     run["run_id"], run["workflow_id"], run["run_by"])
        count += 1
    if count:
        logger.info("Recovered %d crashed workflow runs", count)
    return count


# ---------------------------------------------------------------------------
# QC Workflow Templates (v15.6)
# ---------------------------------------------------------------------------

_QC_TEMPLATES_FILE = os.path.join(
    os.path.dirname(__file__), "standards", "qc_workflow_templates.yaml"
)
_qc_templates_cache: Optional[dict] = None


def load_qc_templates() -> dict[str, dict]:
    """Load QC workflow templates from YAML. Returns {template_id: template_dict}."""
    global _qc_templates_cache
    if _qc_templates_cache is not None:
        return _qc_templates_cache

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed — cannot load QC templates")
        return {}

    if not os.path.isfile(_QC_TEMPLATES_FILE):
        logger.warning("QC templates file not found: %s", _QC_TEMPLATES_FILE)
        return {}

    try:
        with open(_QC_TEMPLATES_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.warning("Failed to load QC templates: %s", e)
        return {}

    templates = {}
    for t in data.get("templates", []):
        tid = t.get("id")
        if tid:
            templates[tid] = t
    _qc_templates_cache = templates
    logger.debug("Loaded %d QC workflow templates", len(templates))
    return templates


def list_qc_templates() -> list[dict]:
    """List available QC workflow templates (summary only)."""
    templates = load_qc_templates()
    return [
        {
            "id": t["id"],
            "name": t.get("name", t["id"]),
            "description": t.get("description", ""),
            "step_count": len(t.get("steps", [])),
            "priority": t.get("priority", "normal"),
            "sla_total_seconds": t.get("sla_total_seconds"),
        }
        for t in templates.values()
    ]


def create_workflow_from_template(
    template_id: str,
    name_override: str = "",
    param_overrides: dict = None,
) -> Optional[int]:
    """Create a workflow instance from a QC template. Returns workflow ID or None."""
    templates = load_qc_templates()
    tmpl = templates.get(template_id)
    if not tmpl:
        return None

    wf_name = name_override or f"{tmpl.get('name', template_id)}_{uuid.uuid4().hex[:6]}"
    params = {}
    for k, v in tmpl.get("parameters", {}).items():
        params[k] = v if not isinstance(v, dict) else v
    if param_overrides:
        for k, v in param_overrides.items():
            if k in params:
                if isinstance(params[k], dict):
                    params[k]["default"] = v
                else:
                    params[k] = v

    engine = get_engine()
    if not engine:
        return None

    username = current_user_id.get() or "system"
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO agent_workflows
                    (workflow_name, description, owner_username, pipeline_type,
                     steps, parameters, sla_total_seconds, priority, template_source)
                VALUES (:name, :desc, :user, :ptype,
                        :steps, :params, :sla, :pri, :src)
                RETURNING id
            """), {
                "name": wf_name,
                "desc": tmpl.get("description", ""),
                "user": username,
                "ptype": tmpl.get("pipeline_type", "governance"),
                "steps": json.dumps(tmpl.get("steps", [])),
                "params": json.dumps(params),
                "sla": tmpl.get("sla_total_seconds"),
                "pri": tmpl.get("priority", "normal"),
                "src": template_id,
            })
            row = result.fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception as e:
        import traceback
        logger.error("Failed to create workflow from template %s: %s", template_id, e)
        logger.error("Traceback: %s", traceback.format_exc())
        return None
