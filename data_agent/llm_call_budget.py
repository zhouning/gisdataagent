"""Persistent admission control for explicitly budgeted model evaluations.

Every dispatched attempt reserves its full approved per-call cost ceiling.
Reservations are never refunded automatically, including on timeout or crash.
The ceiling is an operator-supplied quote for the bounded request profile,
not a price invented from a model name or a substitute for provider billing.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
import uuid


class BudgetDenied(RuntimeError):
    retryable = False

    def __init__(self, code: str):
        self.code = code
        self.evidence = {}
        super().__init__(code)


_active: ContextVar["CallBudget | None"] = ContextVar("llm_call_budget", default=None)
_question: ContextVar[str | None] = ContextVar("llm_budget_question", default=None)


def active_budget():
    return _active.get()


@contextmanager
def use_budget(budget):
    token = _active.set(budget)
    try:
        yield budget
    finally:
        _active.reset(token)


@contextmanager
def budget_question(identity: str):
    token = _question.set(str(identity))
    try:
        yield
    finally:
        _question.reset(token)


def _micros(value, *, ceiling=False):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            raise ValueError
        result = int((amount * 1_000_000).to_integral_value(
            rounding=ROUND_CEILING if ceiling else ROUND_FLOOR))
        if not 0 < result < 2**53:
            raise ValueError
        return result
    except (InvalidOperation, ValueError, OverflowError):
        raise BudgetDenied("budget_invalid_cost") from None


def validate_policy(policy: dict) -> dict:
    fields = {"run_id", "provider", "model", "base_url", "max_calls",
              "max_calls_per_question", "max_output_tokens_per_call",
              "max_total_output_tokens", "max_request_bytes", "max_cost_usd",
              "cost_ceiling_per_call_usd", "pricing_reference", "expires_at"}
    if not isinstance(policy, dict) or set(policy) != fields:
        raise BudgetDenied("budget_policy_fields_required")
    for name in fields - {"max_cost_usd", "cost_ceiling_per_call_usd"}:
        if name.startswith("max_"):
            if type(policy[name]) is not int or not 0 < policy[name] < 2**31:
                raise BudgetDenied("budget_invalid_limit")
        elif not isinstance(policy[name], str) or not policy[name].strip():
            raise BudgetDenied("budget_invalid_identity")
    for name in ("base_url", "pricing_reference"):
        url = urlsplit(policy[name])
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.query or url.fragment):
            raise BudgetDenied("budget_invalid_public_url")
    try:
        expiry = datetime.fromisoformat(policy["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError
    except (ValueError, TypeError):
        raise BudgetDenied("budget_invalid_expiry") from None
    if _micros(policy["cost_ceiling_per_call_usd"], ceiling=True) > _micros(policy["max_cost_usd"]):
        raise BudgetDenied("budget_cost_below_single_call")
    return json.loads(json.dumps(policy, sort_keys=True, allow_nan=False))


def evaluation_budget(out_dir: Path, ledger: Path, policy: dict):
    """Bind resumable evaluation output to one persistent policy and ledger."""
    out_dir, ledger = Path(out_dir), Path(ledger)
    validate_policy(policy)
    if not ledger.is_absolute():
        raise BudgetDenied("budget_ledger_must_be_absolute")
    policy_hash = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    binding = {'policy_sha256':policy_hash, 'run_id':policy['run_id'], 'ledger':str(ledger.resolve())}
    receipt = out_dir/'budget_binding.json'
    if receipt.exists():
        if json.loads(receipt.read_text()) != binding or not ledger.is_file():
            raise BudgetDenied("budget_resume_binding_changed_or_ledger_missing")
    elif (out_dir/'manifest.json').exists() or (out_dir/'records.jsonl').exists():
        raise BudgetDenied("budget_cannot_attach_to_existing_unbudgeted_run")
    budget = CallBudget(ledger, policy)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with receipt.open('x') as handle:
            handle.write(json.dumps(binding,indent=2)+'\n')
    except FileExistsError:
        if json.loads(receipt.read_text()) != binding:
            raise BudgetDenied("budget_resume_binding_changed_or_ledger_missing") from None
    return budget


class CallBudget:
    def __init__(self, ledger: Path, policy: dict):
        self.policy = validate_policy(policy)
        self.ledger = Path(ledger)
        if not self.ledger.is_absolute():
            raise BudgetDenied("budget_ledger_must_be_absolute")
        self.last_denial = None
        self.policy_json = json.dumps(self.policy, sort_keys=True, separators=(",", ":"))
        self.policy_sha256 = hashlib.sha256(self.policy_json.encode()).hexdigest()
        self.run_id = self.policy["run_id"]
        self.cost_per_call = _micros(self.policy["cost_ceiling_per_call_usd"], ceiling=True)
        self.max_cost = _micros(self.policy["max_cost_usd"])
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS model_budget_runs (run_id TEXT PRIMARY KEY, policy TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS model_budget_calls (
                call_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, question_hash TEXT NOT NULL,
                reserved_usd_micros INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                request_bytes INTEGER NOT NULL, request_sha256 TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, usage_json TEXT)""")
            db.execute("CREATE INDEX IF NOT EXISTS model_budget_run_idx ON model_budget_calls(run_id, question_hash)")
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO model_budget_runs VALUES (?, ?)", (self.run_id, self.policy_json))
            if db.execute("SELECT policy FROM model_budget_runs WHERE run_id=?", (self.run_id,)).fetchone()[0] != self.policy_json:
                raise BudgetDenied("budget_policy_changed")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.ledger), timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _deny(self, code):
        self.last_denial = code
        raise BudgetDenied(code)

    def reserve(self, config, request: dict):
        p = self.policy
        if json.dumps(p, sort_keys=True, separators=(',', ':')) != self.policy_json:
            self._deny("budget_policy_changed")
        if (config.provider, config.model, config.base_url) != (p['provider'], p['model'], p['base_url']):
            self._deny("budget_model_or_endpoint_changed")
        if not _question.get():
            self._deny("budget_question_identity_required")
        now = datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(p['expires_at'].replace('Z', '+00:00'))
        if now >= expiry:
            self._deny("budget_expired")
        output = request.get('max_output_tokens', request.get('max_completion_tokens', request.get('max_tokens')))
        if type(output) is not int or output <= 0 or output > p['max_output_tokens_per_call']:
            self._deny("budget_output_limit")
        raw = json.dumps(request, ensure_ascii=False, sort_keys=True).encode()
        if len(raw) > p['max_request_bytes']:
            self._deny("budget_request_size_limit")
        question_hash = hashlib.sha256(_question.get().encode()).hexdigest()
        call_id = uuid.uuid4().hex
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                # Re-read immutable policy inside admission's transaction.
                row = db.execute("SELECT policy FROM model_budget_runs WHERE run_id=?", (self.run_id,)).fetchone()
                if not row or row[0] != self.policy_json:
                    self._deny("budget_policy_changed")
                count, cost, tokens = db.execute(
                    "SELECT COUNT(*),COALESCE(SUM(reserved_usd_micros),0),COALESCE(SUM(output_tokens),0) FROM model_budget_calls WHERE run_id=?",
                    (self.run_id,)).fetchone()
                qcount = db.execute("SELECT COUNT(*) FROM model_budget_calls WHERE run_id=? AND question_hash=?",
                                    (self.run_id, question_hash)).fetchone()[0]
                if count >= p['max_calls']:
                    self._deny("budget_call_limit")
                if qcount >= p['max_calls_per_question']:
                    self._deny("budget_question_call_limit")
                if cost + self.cost_per_call > self.max_cost:
                    self._deny("budget_cost_limit")
                if tokens + output > p['max_total_output_tokens']:
                    self._deny("budget_total_output_limit")
                db.execute("INSERT INTO model_budget_calls VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                           (call_id, self.run_id, question_hash, self.cost_per_call, output,
                            len(raw), hashlib.sha256(raw).hexdigest(), 'reserved', now.isoformat()))
        except sqlite3.Error:
            self._deny("budget_ledger_unavailable")
        return {"call_id": call_id, "run_id": self.run_id, "policy_sha256": self.policy_sha256,
                "reserved_usd_micros": self.cost_per_call}

    def finish(self, reservation, status, usage=None):
        # Store only allowlisted usage values; never prompts, keys or errors.
        names = ('prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens')
        safe_usage = {}
        for name in names:
            value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
            if type(value) is int and value >= 0:
                safe_usage[name] = value
        try:
            with self._connect() as db:
                db.execute("UPDATE model_budget_calls SET status=?,usage_json=? WHERE call_id=? AND run_id=?",
                           (status, json.dumps(safe_usage), reservation['call_id'], self.run_id))
        except sqlite3.Error:
            self._deny("budget_ledger_unavailable_after_dispatch")

    def snapshot(self):
        with self._connect() as db:
            count, cost, tokens = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(reserved_usd_micros),0),COALESCE(SUM(output_tokens),0) FROM model_budget_calls WHERE run_id=?",
                (self.run_id,)).fetchone()
            statuses = dict(db.execute("SELECT status,COUNT(*) FROM model_budget_calls WHERE run_id=? GROUP BY status", (self.run_id,)))
        return {"run_id": self.run_id, "policy_sha256": self.policy_sha256,
                "reserved_calls": count, "reserved_cost_usd": str(Decimal(cost) / 1_000_000),
                "reserved_output_tokens": tokens, "statuses": statuses,
                "last_denial": self.last_denial, "billing_status": "reserved_ceiling_not_provider_bill"}
