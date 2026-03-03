"""
Workflow Engine — Multi-step pipeline workflows with scheduling and webhook push.

v5.4: Users create reusable workflows that chain pipeline executions,
run them manually or on a cron schedule, and push results via webhook.
"""
import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import text

from .db_engine import get_engine
from .user_context import current_user_id, current_session_id, current_user_role


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
                        :steps::jsonb, :params::jsonb, :graph::jsonb,
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
            set_clauses.append(f"{k} = :{k}::jsonb")
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
) -> dict:
    """Execute a workflow: run each step sequentially via pipeline_runner.

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
                    VALUES (:wf_id, :user, 'running', :params::jsonb)
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

    for i, step in enumerate(steps):
        step_id = step.get("step_id", f"step_{i}")
        pipeline_type = step.get("pipeline_type", "general")
        prompt = _substitute_params(step.get("prompt", ""), params)
        intent = pipeline_type.upper()

        # Select agent
        agent_obj = _get_agent_for_pipeline(agent_module, pipeline_type)
        if not agent_obj:
            error_msg = f"Unknown pipeline_type: {pipeline_type}"
            status = "failed"
            break

        try:
            result = await run_pipeline_headless(
                agent=agent_obj,
                session_service=session_service,
                user_id=user,
                session_id=f"{session_id}_{step_id}",
                prompt=prompt,
                pipeline_type=pipeline_type,
                intent=intent,
                role="analyst",
            )
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
            })
            total_input += result.total_input_tokens
            total_output += result.total_output_tokens

            if result.error:
                error_msg = f"Step '{step_id}' failed: {result.error}"
                status = "failed"
                break
        except Exception as e:
            error_msg = f"Step '{step_id}' exception: {str(e)}"
            status = "failed"
            step_results.append({
                "step_id": step_id,
                "label": step.get("label", step_id),
                "status": "failed",
                "error": str(e),
            })
            break

    duration = time.time() - start_time

    # Update run record
    webhook_sent = False
    if engine and run_id:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    UPDATE {T_WORKFLOW_RUNS}
                    SET status = :status, step_results = :results::jsonb,
                        total_duration = :dur, total_input_tokens = :inp,
                        total_output_tokens = :out, error_message = :err,
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


def _get_agent_for_pipeline(agent_module, pipeline_type: str):
    """Get the appropriate agent for a pipeline type."""
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
