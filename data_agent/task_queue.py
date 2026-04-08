"""
Concurrent Task Queue — background pipeline execution with concurrency control (v11.0.1).

Manages parallel pipeline runs via asyncio.Semaphore, priority queue, and
lifecycle tracking. Integrates with run_pipeline_headless() for execution.

v20.0: Redis backend for distributed queue (sorted set + distributed semaphore).
Falls back to in-memory when Redis is unavailable.

All DB operations are non-fatal (never raise to caller).
"""
import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine

try:
    from .observability import get_logger
    logger = get_logger("task_queue")
except Exception:
    import logging
    logger = logging.getLogger("task_queue")


T_TASK_QUEUE = "agent_task_queue"
MAX_CONCURRENT = int(os.environ.get("TASK_QUEUE_CONCURRENCY", "3"))
MAX_QUEUED_PER_USER = int(os.environ.get("TASK_QUEUE_MAX_PER_USER", "10"))

# Redis key prefixes
_RK_QUEUE = "agent:task_queue"          # Sorted set (priority queue)
_RK_JOB = "agent:task:"                 # Hash per job: agent:task:{job_id}
_RK_SEMAPHORE = "agent:task_semaphore"  # Distributed semaphore counter


T_TASK_QUEUE = "agent_task_queue"
MAX_CONCURRENT = int(os.environ.get("TASK_QUEUE_CONCURRENCY", "3"))
MAX_QUEUED_PER_USER = int(os.environ.get("TASK_QUEUE_MAX_PER_USER", "10"))


def _get_pipeline_agent(pipeline_type: str):
    """Get the appropriate ADK agent for a pipeline type."""
    from . import agent as agent_module
    mapping = {
        "general": "general_pipeline",
        "governance": "governance_pipeline",
        "optimization": "data_pipeline",
        "planner": "planner_agent",
    }
    attr = mapping.get(pipeline_type, "general_pipeline")
    return getattr(agent_module, attr, None)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TaskJob:
    """A single pipeline task in the queue."""
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = ""
    prompt: str = ""
    pipeline_type: str = "general"
    status: str = "queued"  # queued | running | completed | failed | cancelled
    priority: int = 5  # 0 (highest) - 9 (lowest)
    role: str = "analyst"
    result_summary: str = ""
    error_message: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    duration: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "user_id": self.user_id,
            "prompt": self.prompt[:200],  # truncate for listing
            "pipeline_type": self.pipeline_type,
            "status": self.status,
            "priority": self.priority,
            "result_summary": self.result_summary[:500] if self.result_summary else "",
            "error_message": self.error_message,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration": round(self.duration, 2),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ---------------------------------------------------------------------------
# Task Queue
# ---------------------------------------------------------------------------

class TaskQueue:
    """Concurrent pipeline task queue with Redis or in-memory backend.

    Redis backend (v20.0): Sorted set for priority queue, Hash for job state,
    SETNX-based distributed semaphore for concurrency control.
    Memory backend: asyncio.PriorityQueue + asyncio.Semaphore (single-node).
    """

    def __init__(self, max_concurrent: int = MAX_CONCURRENT):
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._jobs: dict[str, TaskJob] = {}
        self._pending: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown = False
        self._use_redis = False
        self._redis = None

    # ----- Lifecycle -----

    def start(self):
        """Start the worker loop."""
        if self._worker_task is not None:
            return
        self._shutdown = False
        self._ensure_table()
        self._init_redis()
        self._worker_task = asyncio.ensure_future(self._worker_loop())
        backend = "Redis" if self._use_redis else "in-memory"
        logger.info("Task queue started (max_concurrent=%d, backend=%s)", self._max_concurrent, backend)

    def _init_redis(self):
        """Try to connect to Redis for distributed queue."""
        try:
            from .redis_client import get_redis_sync
            r = get_redis_sync()
            if r:
                self._redis = r
                self._use_redis = True
                logger.info("Task queue using Redis backend")
            else:
                self._use_redis = False
        except Exception as e:
            logger.debug("Redis not available for task queue: %s", e)
            self._use_redis = False

    async def stop(self):
        """Stop the worker loop and cancel running tasks."""
        self._shutdown = True
        if self._worker_task:
            self._worker_task.cancel()
            self._worker_task = None
        for job_id, task in list(self._running_tasks.items()):
            task.cancel()
        self._running_tasks.clear()
        logger.info("Task queue stopped")

    # ----- DB table -----

    def _ensure_table(self):
        engine = get_engine()
        if not engine:
            return
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {T_TASK_QUEUE} (
                        id SERIAL PRIMARY KEY,
                        job_id VARCHAR(36) UNIQUE NOT NULL,
                        user_id VARCHAR(100) NOT NULL,
                        prompt TEXT NOT NULL,
                        pipeline_type VARCHAR(30) DEFAULT 'general',
                        status VARCHAR(20) DEFAULT 'queued',
                        priority INTEGER DEFAULT 5,
                        result_summary TEXT,
                        error_message TEXT,
                        input_tokens INTEGER DEFAULT 0,
                        output_tokens INTEGER DEFAULT 0,
                        duration REAL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT NOW(),
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                """))
                conn.commit()
        except Exception as e:
            logger.warning("Failed to create task_queue table: %s", e)

    def _persist_job(self, job: TaskJob):
        """Write-through: update job state in DB."""
        engine = get_engine()
        if not engine:
            return
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    INSERT INTO {T_TASK_QUEUE}
                        (job_id, user_id, prompt, pipeline_type, status, priority,
                         result_summary, error_message, input_tokens, output_tokens,
                         duration, started_at, completed_at)
                    VALUES (:jid, :uid, :prompt, :pt, :status, :pri,
                            :summary, :err, :itok, :otok, :dur, :started, :completed)
                    ON CONFLICT (job_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        result_summary = EXCLUDED.result_summary,
                        error_message = EXCLUDED.error_message,
                        input_tokens = EXCLUDED.input_tokens,
                        output_tokens = EXCLUDED.output_tokens,
                        duration = EXCLUDED.duration,
                        started_at = EXCLUDED.started_at,
                        completed_at = EXCLUDED.completed_at
                """), {
                    "jid": job.job_id, "uid": job.user_id, "prompt": job.prompt,
                    "pt": job.pipeline_type, "status": job.status, "pri": job.priority,
                    "summary": job.result_summary, "err": job.error_message,
                    "itok": job.input_tokens, "otok": job.output_tokens,
                    "dur": job.duration,
                    "started": datetime.fromtimestamp(job.started_at, tz=timezone.utc) if job.started_at else None,
                    "completed": datetime.fromtimestamp(job.completed_at, tz=timezone.utc) if job.completed_at else None,
                })
                conn.commit()
        except Exception as e:
            logger.debug("Failed to persist job %s: %s", job.job_id, e)

    # ----- Public API -----

    def submit(self, user_id: str, prompt: str, pipeline_type: str = "general",
               priority: int = 5, role: str = "analyst") -> str:
        """Submit a new task. Returns job_id."""
        # Check per-user queue limit
        user_active = sum(1 for j in self._jobs.values()
                         if j.user_id == user_id and j.status in ("queued", "running"))
        if user_active >= MAX_QUEUED_PER_USER:
            raise ValueError(f"User queue limit ({MAX_QUEUED_PER_USER}) reached")

        job = TaskJob(
            user_id=user_id, prompt=prompt, pipeline_type=pipeline_type,
            priority=max(0, min(9, priority)), role=role,
        )
        self._jobs[job.job_id] = job

        if self._use_redis and self._redis:
            try:
                # Store job data in Redis Hash
                self._redis.hset(
                    f"{_RK_JOB}{job.job_id}",
                    mapping={"data": json.dumps(job.to_dict()), "status": "queued"},
                )
                self._redis.expire(f"{_RK_JOB}{job.job_id}", 86400)  # 24h TTL
                # Add to sorted set (score = priority * 1e10 + created_at for stable sort)
                score = job.priority * 1e10 + job.created_at
                self._redis.zadd(_RK_QUEUE, {job.job_id: score})
                logger.debug("Job %s enqueued to Redis (score=%.0f)", job.job_id, score)
            except Exception as e:
                logger.warning("Redis enqueue failed, using memory: %s", e)
                self._pending.put_nowait((job.priority, job.created_at, job.job_id))
        else:
            self._pending.put_nowait((job.priority, job.created_at, job.job_id))

        self._persist_job(job)
        logger.info("Task submitted: %s (user=%s, pipeline=%s)", job.job_id, user_id, pipeline_type)
        return job.job_id

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued or running task."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status == "queued":
            job.status = "cancelled"
            job.completed_at = time.time()
            self._persist_job(job)
            return True
        if job.status == "running":
            task = self._running_tasks.get(job_id)
            if task:
                task.cancel()
            job.status = "cancelled"
            job.completed_at = time.time()
            self._persist_job(job)
            return True
        return False

    def get_status(self, job_id: str) -> Optional[dict]:
        """Get job status dict (checks memory first, then Redis)."""
        job = self._jobs.get(job_id)
        if job:
            return job.to_dict()
        # Check Redis if not in memory (e.g., submitted by another instance)
        if self._use_redis and self._redis:
            try:
                data = self._redis.hget(f"{_RK_JOB}{job_id}", "data")
                if data:
                    return json.loads(data)
            except Exception:
                pass
        return None

    def list_jobs(self, user_id: str = None, status: str = None, limit: int = 20) -> list[dict]:
        """List jobs, optionally filtered by user and/or status."""
        jobs = list(self._jobs.values())
        if user_id:
            jobs = [j for j in jobs if j.user_id == user_id]
        if status:
            jobs = [j for j in jobs if j.status == status]
        # Sort by created_at descending
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    @property
    def queue_stats(self) -> dict:
        """Current queue statistics."""
        statuses = {}
        for j in self._jobs.values():
            statuses[j.status] = statuses.get(j.status, 0) + 1
        return {
            "total": len(self._jobs),
            "max_concurrent": self._max_concurrent,
            "by_status": statuses,
        }

    # ----- Worker -----

    async def _worker_loop(self):
        """Dequeue and execute jobs with semaphore concurrency control.

        Redis backend: ZPOPMIN from sorted set + distributed semaphore.
        Memory backend: asyncio.PriorityQueue + asyncio.Semaphore.
        """
        while not self._shutdown:
            try:
                job_id = None

                if self._use_redis and self._redis:
                    # Redis: pop lowest-score job from sorted set
                    try:
                        result = self._redis.zpopmin(_RK_QUEUE, count=1)
                        if result:
                            job_id = result[0][0]  # (member, score)
                        else:
                            await asyncio.sleep(1)
                            continue
                    except Exception as e:
                        logger.debug("Redis dequeue error: %s", e)
                        await asyncio.sleep(2)
                        continue
                else:
                    # Memory: wait for next job with timeout
                    try:
                        priority, created_at, job_id = await asyncio.wait_for(
                            self._pending.get(), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue

                job = self._jobs.get(job_id)
                if not job or job.status == "cancelled":
                    continue

                # Acquire semaphore (blocks if at max concurrency)
                await self._semaphore.acquire()
                task = asyncio.ensure_future(self._execute_job(job))
                self._running_tasks[job_id] = task

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Worker loop error: %s", e)
                await asyncio.sleep(1)

    async def _execute_job(self, job: TaskJob):
        """Execute a single job and update its state."""
        try:
            job.status = "running"
            job.started_at = time.time()
            self._persist_job(job)

            # Import and run pipeline
            from .pipeline_runner import run_pipeline_headless
            from google.adk.sessions import InMemorySessionService

            agent = _get_pipeline_agent(job.pipeline_type)
            session_service = InMemorySessionService()
            session_id = f"task_{job.job_id}"

            result = await run_pipeline_headless(
                agent=agent,
                session_service=session_service,
                user_id=job.user_id,
                session_id=session_id,
                prompt=job.prompt,
                pipeline_type=job.pipeline_type,
                role=job.role,
            )

            job.status = "completed" if not result.error else "failed"
            job.result_summary = result.report_text[:2000] if result.report_text else ""
            job.error_message = result.error or ""
            job.input_tokens = result.total_input_tokens
            job.output_tokens = result.total_output_tokens
            job.duration = result.duration_seconds

        except asyncio.CancelledError:
            job.status = "cancelled"
        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)[:500]
            logger.warning("Task %s failed: %s", job.job_id, e)
        finally:
            job.completed_at = time.time()
            if not job.duration and job.started_at:
                job.duration = job.completed_at - job.started_at
            self._persist_job(job)
            # Update Redis job state
            if self._use_redis and self._redis:
                try:
                    self._redis.hset(
                        f"{_RK_JOB}{job.job_id}",
                        mapping={"data": json.dumps(job.to_dict()), "status": job.status},
                    )
                except Exception:
                    pass
            self._running_tasks.pop(job.job_id, None)
            self._semaphore.release()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    """Get or create the singleton TaskQueue."""
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue


def reset_task_queue():
    """Reset the singleton. Used for testing."""
    global _queue
    _queue = None
