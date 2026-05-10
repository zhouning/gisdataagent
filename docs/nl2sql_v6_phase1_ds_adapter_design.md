# NL2SQL v6 Phase 1 — DeepSeek Adapter Design

**Date**: 2026-05-10
**Goal**: Make NL2Semantic2SQL pass the gate (within-family Δ ≥ +0.08 EX, paired McNemar p < 0.10) on **both** Gemini-2.5-Flash and DeepSeek-V4-Flash, without regressing Gemini.
**Input evidence**: `docs/nl2sql_v6_phase0_diagnosis.md` + `docs/nl2sql_v6_phase1_error_attribution.md` (51 records / 17 grounding-reversal qids).

---

## Design principles

1. **Knowledge stays in one place**. Domain rules (SRID semantics, OGC predicate definitions, PostGIS function catalog, safety constraints) are **family-agnostic** and live in `prompts/common/`. We do not duplicate them per family.
2. **Presentation is per-family**. *How* we communicate rules to a model depends on its instruction-following profile — long narrative bullets work for Gemini, short directive imperatives + concrete examples work for DeepSeek. Live in `prompts/{gemini,deepseek}/`.
3. **No regression on Gemini**. Gemini's existing prompt is the reference implementation. New abstractions must reproduce its current behavior bit-for-bit on the Gemini path.
4. **Evidence-driven, not aesthetic**. Every adapter rule maps to an attribution bucket (A-G) from Phase 0 / Phase 1 error-attribution analysis. No speculative rules.
5. **Runtime guards complement prompts, not replace them**. Some failure modes (CSV path hallucination, give-up SQL) are best caught post-hoc with cheap regex guards rather than instructed away. Defense-in-depth.

---

## What changes vs. current state

### Current code (D:\adk, on `feat/v12-extensible-platform`)
- `data_agent/prompts/*.yaml` — 5 YAML files for the **legacy 3-pipeline app**, NOT for nl2sql_agent.py. The NL2SQL eval agent's instruction is **hardcoded inside `scripts/nl2sql_bench_cq/nl2sql_agent.py`** (lines 23-58).
- `data_agent/nl2sql_grounding.py` — produces a `_format_grounding_prompt()` payload that gets appended to the agent context. Contains the long Chinese rule blocks (security, KNN, aggregation, DISTINCT) gated on `IntentLabel`.
- `data_agent/nl2sql_intent.py` — rule-based + LLM-judge intent classifier. Used by `_format_grounding_prompt` to decide which rule blocks to emit.
- `data_agent/sql_postprocessor.py` — postprocessor (unrelated to per-family adaptation; stays untouched in Phase 1).

### Phase 1 scope
**This phase touches NL2SQL evaluation path only**, not the production `data_agent.app` chainlit UI. The 5 YAML files in `data_agent/prompts/` are out-of-scope for now. We touch:

- `scripts/nl2sql_bench_cq/nl2sql_agent.py` — instruction selection becomes per-family
- `data_agent/nl2sql_grounding.py` — rule emission becomes per-family aware
- `data_agent/nl2sql_intent.py` — gain a "bypass" path for families where intent routing is net-negative
- New: `data_agent/prompts_nl2sql/` — namespace dir for per-family templates
- New: `data_agent/runtime_guards.py` — small post-hoc SQL guards (give-up SQL, hallucinated table names)
- `data_agent/model_gateway.py` — exposes `family_name(model_obj)` so callers can pick prompt namespace

---

## Directory layout

```
data_agent/
  prompts_nl2sql/
    common/
      domain_facts.md          # PostGIS predicates, SRID conventions, ROUND syntax, KNN operator — family-invariant
      schema_quoting_rules.md  # uppercase column quoting, table aliases — family-invariant
      bounded_output_policy.md # safe-refusal / LIMIT 1000 fallback — family-invariant
    gemini/
      system_instruction.md    # current 5-step Mandatory Workflow (verbatim from nl2sql_agent.py L23-58)
      grounding_template.md    # current _format_grounding_prompt output (verbatim)
      few_shots.yaml           # references to fetch_nl2sql_few_shots config
    deepseek/
      system_instruction.md    # NEW: short, directive-style instruction (see §4 below)
      grounding_template.md    # NEW: bullet-light, example-heavy grounding payload
      few_shots.yaml           # NEW: hand-curated DS positive examples covering buckets A/B/D/E
  runtime_guards.py            # NEW: detect_give_up_sql(), detect_hallucinated_table_name(), strip_format_wrappers()
  nl2sql_intent.py             # MODIFIED: respect NL2SQL_INTENT_FAMILY env / per-family bypass
  nl2sql_grounding.py          # MODIFIED: emit family-tagged rule blocks; load template from prompts_nl2sql/<family>/
scripts/nl2sql_bench_cq/
  nl2sql_agent.py              # MODIFIED: select instruction file based on detected family
```

---

## Component design

### 1. Family detection (`data_agent/model_gateway.py`)

Add a small helper:

```python
def family_of(model_obj) -> str:
    """Return 'gemini' | 'deepseek' | 'litellm' | 'lm_studio' | 'unknown'."""
    cls = type(model_obj).__name__
    if cls == "Gemini":
        return "gemini"
    if cls == "LiteLlm":
        # discriminate by model string set on the LiteLlm instance
        m = getattr(model_obj, "model", "") or ""
        if "deepseek" in m.lower():
            return "deepseek"
        if "lm_studio" in m.lower() or m.startswith("openai/") and "1234" in os.environ.get("OPENAI_API_BASE", ""):
            return "lm_studio"
        return "litellm"
    return "unknown"
```

This is the single source of truth for "which family is this LLM?". All callers go through it; no string sniffing scattered around.

### 2. Per-family system instruction (`scripts/nl2sql_bench_cq/nl2sql_agent.py`)

```python
def build_nl2sql_agent():
    from data_agent.model_gateway import create_model, family_of
    from data_agent.prompts_nl2sql import load_system_instruction

    model_name = os.environ.get("NL2SQL_AGENT_MODEL", "gemini-2.5-flash")
    model_obj = create_model(model_name)
    family = family_of(model_obj)
    instruction = load_system_instruction(family)  # falls back to gemini/ if family unknown

    return LlmAgent(
        name="NL2SQLEvalAgent",
        instruction=instruction,
        ...
    )
```

The current hardcoded 36-line instruction string moves verbatim to `prompts_nl2sql/gemini/system_instruction.md`. Zero behavior change on Gemini.

### 3. DeepSeek system instruction (NEW)

Rules below are derived from the 7 attribution buckets. Every rule maps to a bucket; nothing speculative.

```markdown
You are a PostgreSQL/PostGIS SQL generator. For each question, you MUST produce
exactly one valid SELECT and execute it via the `query_database` tool.

## OUTPUT CONTRACT (strict — every rule is enforced)

R1. SELECT only the columns the user explicitly asked for.
    Do NOT add WHERE-used columns, do NOT add primary-key columns, do NOT add
    "context" columns even if helpful. If the question says "name", SELECT
    only the name column.
    [bucket A: projection drift — 17/51 records]

R2. The aggregation must match the question.
    "多少 / how many / 数量 / 统计" → COUNT(*). Do not return a listing.
    "几种 / DISTINCT" → COUNT(DISTINCT col). Do not return a list of values.
    "GROUP BY" / "按...分组" → aggregation with GROUP BY.
    Do not "improve" the question's intent.
    [bucket B: intent over-interpretation — 12/51 records]

R3. Do not wrap aggregation results.
    Use AVG(col), not ROUND(AVG(col), 2).
    Use SUM(col), not COALESCE(SUM(col), 0).
    Use raw column references, not CAST AS TEXT.
    Wrap with formatters ONLY when the question explicitly says
    "保留 N 位小数" / "rounded to N decimals".
    [bucket D: numeric formatting — 5/51 records]

R4. Predicates match the question's geometry vocabulary.
    "相交 / intersects" → ST_Intersects(a.geometry, b.geometry).
    "包含 / contains" → ST_Contains.
    "落在...内 / within" → ST_Within.
    "距离 X 米内" → ST_DWithin(a::geography, b::geography, X).
    Do NOT substitute ST_DWithin with a small numeric threshold for
    intersection. Do NOT pick the operator yourself.
    [bucket E: over-engineering predicates — 5/51 records]

R5. Use only the table names listed in the SCHEMA section below.
    Reject any table name that contains: a slash "/", backslash "\\",
    ".csv" suffix, the substring "query_result_", or "uploads".
    Such strings are file paths, not tables.
    [bucket F: hallucinated table name — 3/51 records]

R6. Always call `query_database` with the SQL exactly once.
    Never emit `SELECT 1 AS test` or other placeholder SQL — if you cannot
    answer, refuse with a one-sentence explanation in plain text. Do not
    submit a placeholder query.
    [bucket G: give-up SQL — 2/51 records]

R7. The first tool call MUST be `resolve_semantic_context` with the
    user's question. Wait for its return. Then call `describe_table_semantic`
    only if column names need clarification. Then call `query_database` once.
    Do NOT explore the schema beyond these three calls.
    [bucket C: silent refusal / EMPTY — 7/51 records, mitigates loop blowup]

## DOMAIN FACTS

(Imported verbatim from prompts_nl2sql/common/domain_facts.md — same content
on all families)

## SCHEMA

(Injected by runner per-question)
```

**Why this works on DS but Gemini's instruction works on Gemini**:

- Gemini's instruction uses **narrative + 5-step workflow + "CRITICAL"-style emphasis**. Gemini follows that style well.
- DS instruction uses **numbered rules R1..R7, each ≤4 lines, each tied to a concrete failure pattern**. DS's instruction-following profile responds to imperative compact rules better than to long narrative.
- Both reference the same underlying domain facts via `prompts_nl2sql/common/`.

### 4. Per-family grounding payload (`data_agent/nl2sql_grounding.py`)

Modify `_format_grounding_prompt` to accept a `family: str` parameter:

```python
def _format_grounding_prompt(payload: dict, family: str = "gemini") -> str:
    # ... compute everything as before ...
    template_path = f"prompts_nl2sql/{family}/grounding_template.md"
    if not (ROOT / template_path).exists():
        template_path = "prompts_nl2sql/gemini/grounding_template.md"  # fallback
    # ... render template with payload ...
```

The Gemini `grounding_template.md` is the verbatim current output of `_format_grounding_prompt`. The DeepSeek version is shorter — rule blocks become 1-2-line bullets and KNN/Aggregation/DISTINCT sections become single-paragraph imperatives.

Caller (`build_nl2sql_context()` in same file) reads family from a thread-local set by the agent factory, or falls back to `gemini`.

### 5. Intent router bypass for DS (`data_agent/nl2sql_intent.py`)

**The decisive evidence** from error attribution: on the 17 grounding-reversal qids, baseline (no intent router) was 17/17 correct and full (with intent router) was 17/17 wrong. **Intent classifier is net-negative on DS for several common patterns** (CQ_GEO_EASY_12, EASY_17, HARD_08 all misclassified by the LLM judge stage).

Cheapest robust fix: make intent classification gated by family.

```python
def classify_intent(question: str, family: str = "gemini") -> IntentResult:
    if os.environ.get("NL2SQL_DISABLE_INTENT") == "1":
        return IntentResult(primary=IntentLabel.UNKNOWN, confidence=0.0, source="disabled")
    if family == "deepseek":
        # rule stage only; never call LLM judge.
        # DS prompt R2 handles aggregation/listing distinction directly via
        # surface-form keywords from the question.
        return classify_rule(question)
    # gemini and other families: rule + LLM judge, as before
    rule = classify_rule(question)
    if rule.primary is not IntentLabel.UNKNOWN and rule.confidence >= 0.7:
        return rule
    try:
        return _llm_judge(question)
    except Exception:
        return IntentResult(primary=IntentLabel.UNKNOWN, confidence=0.0, source="fallback")
```

**Why not bypass intent entirely for DS?** Rule-stage intent is cheap and accurate for KNN / SPATIAL_JOIN / REFUSAL — keep it. Only the LLM-judge stage (which is where the misclassifications happen for COUNT/aggregation questions) is removed for DS. The DS prompt's R2 rule then handles aggregation distinction by direct keyword on the question.

### 6. Runtime guards (`data_agent/runtime_guards.py`)

Three lightweight post-hoc checks called right before `query_database` execution. They run for **all families** (defense-in-depth).

```python
def detect_give_up_sql(sql: str) -> bool:
    """Returns True if SQL is a placeholder like SELECT 1 AS test."""
    s = re.sub(r"\s+", " ", sql.strip().lower()).rstrip(";")
    if not s.startswith("select"):
        return False
    return bool(re.match(
        r"select\s+1(\s+as\s+\w+)?(\s+from\s+\(?\s*select\s+\d+\s*\)?)?\s*(limit\s+\d+)?$",
        s,
    ))

def detect_hallucinated_table_name(sql: str, allowed_tables: set[str]) -> str | None:
    """Returns the offending hallucinated table name, or None."""
    # FROM/JOIN tokenizer
    matches = re.findall(r"(?:from|join)\s+([\"`\w\\\\/.]+)", sql, re.IGNORECASE)
    for m in matches:
        bare = m.strip('"`').lstrip("public.")
        if any(bad in bare for bad in ("/", "\\", ".csv", "query_result_", "uploads")):
            return bare
        if allowed_tables and bare not in allowed_tables and not bare.startswith("("):
            return bare
    return None

def is_safe_sql(sql: str, allowed_tables: set[str]) -> tuple[bool, str]:
    """Returns (ok, reason). Use as last gate before execution."""
    if detect_give_up_sql(sql):
        return False, "give_up_placeholder"
    halluc = detect_hallucinated_table_name(sql, allowed_tables)
    if halluc:
        return False, f"hallucinated_table:{halluc}"
    return True, "ok"
```

Hooked into `nl2sql_grounding` or wherever the runner extracts pred_sql before execution. On detection: rec is marked with `valid=0, reason="<guard_label>"` and **the agent gets a chance to retry** (one extra turn). This Fix 1 (runner text-fallback) plus this guard becomes a complete extraction pipeline.

### 7. Few-shot DS-specific catalog (`prompts_nl2sql/deepseek/few_shots.yaml`)

5 hand-curated DS positive examples to seed in-context learning, one per high-volume bucket:

| # | Bucket | Example |
|---|---|---|
| 1 | A (projection) | Q: "列出 DLMC='水田' 的图斑面积" → `SELECT "TBMJ" FROM cq_land_use_dltb WHERE "DLMC"='水田'` (single column only) |
| 2 | B (intent) | Q: "统计有多少个建筑" → `SELECT COUNT(*) FROM cq_buildings_2021` (NOT a listing) |
| 3 | D (no wrapping) | Q: "Floor 字段的最大值/最小值/平均值" → `SELECT MAX("Floor"), MIN("Floor"), AVG("Floor") FROM cq_buildings_2021` (no ROUND) |
| 4 | E (predicate) | Q: "与道路相交的水田" → `... ON ST_Intersects(l.geometry, r.geometry)` (ST_Intersects, not ST_DWithin) |
| 5 | KNN | Q: "距离 POI X 最近的 5 条道路" → `... ORDER BY r.geometry <-> p.geometry LIMIT 5` (KNN operator, not ST_Distance) |

These are appended to DS prompt only. Gemini few-shots come from the existing embedding-based retrieval (`fetch_nl2sql_few_shots`) — unchanged.

---

## Verification plan

After Phase 1 implementation, run **two** N=3 evaluations:

| Cell | Purpose | Cost |
|---|---|---|
| DS full × N=3 (Phase 1) | Validate against Fix 0 baseline | ~3 hr |
| Gemini full × N=3 (Phase 1) | Confirm zero regression | ~2 hr |

Then `stats_cross_family_85q.py` to compute paired McNemar:

**Pass conditions** (both must hold):
- DS within-family: Δ EX (full vs baseline MV) ≥ +0.08, paired exact p < 0.10
- Gemini within-family: Δ EX ≥ +0.10 (current is +0.129); p ≤ 0.10 (current is 0.052) — must NOT regress

**If Gemini regresses** (e.g. p > 0.15 or Δ < +0.08): roll back. Most likely cause would be the new code path leaks DS-shaped rules into Gemini's prompt. Bisect by reverting `prompts_nl2sql/gemini/*.md` to the original verbatim text.

**If DS doesn't pass** but Gemini still passes: investigate which buckets weren't fixed and decide between (a) Phase 1.5 — refine the DS rules; (b) escalate to the prompt-IR + per-family adapter machinery sketched in v6 phase 0 doc; (c) admit the gain is below the gate and revisit error attribution for new buckets.

---

## Out of scope for Phase 1

- Production `data_agent.app` chainlit UI prompts (`data_agent/prompts/*.yaml`)
- Third-family validation (Qwen / GPT-4 / Claude) — Phase 3 work
- Fix 1 runner text-fallback SQL extraction — Phase 2 work, but coordinated with this design (the runtime_guards module is shared)
- Postprocessor changes — `sql_postprocessor.py` is family-agnostic and stays untouched
- Token cost optimization beyond what naturally falls out of shorter DS instruction

---

## Implementation order (concrete)

1. **Scaffold prompts_nl2sql/ namespace** — create directory, copy verbatim text into `gemini/` files, write `__init__.py` with `load_system_instruction(family)` loader.  *No behavior change yet.*
2. **Add `family_of()` to `model_gateway.py`** — single line of test added to confirm Gemini→"gemini", DS→"deepseek".  *Pure addition, zero behavior change.*
3. **Switch `nl2sql_agent.py` to read instruction from filesystem** via the loader.  *Verify Gemini probe still produces identical results — diff the output of one run vs main branch.*
4. **Author `prompts_nl2sql/deepseek/system_instruction.md`** based on the R1-R7 rules above.  *Run 1-q DS probe on `CQ_GEO_EASY_12` (the COUNT misclassification case) to confirm the new prompt produces correct SQL.*
5. **Add `family_of()` parameter to `classify_intent` + `build_nl2sql_context`**, default `gemini`, plumb through `nl2sql_agent.py`.  *Verify Gemini path unchanged.*
6. **Author `prompts_nl2sql/deepseek/grounding_template.md`** — DS-tuned rendering.  *1-q probe on a Hard qid (CQ_GEO_HARD_08 — bridge GROUP BY case).*
7. **Author `prompts_nl2sql/deepseek/few_shots.yaml`** — 5 examples.  *1-q smoke test confirming few-shot injection works.*
8. **Author `runtime_guards.py`** + unit tests for the 3 guards.  *Pytest passes.*
9. **Wire `runtime_guards.is_safe_sql()` into the SQL extraction path** in `run_cq_eval.py:341`.  *1-q probe on a known give-up case (CQ_GEO_HARD_03 s3).*
10. **Run DS full × N=3** with new adapter → stats.
11. **Run Gemini full × N=3** with new code paths → stats. *Confirm no regression.*
12. **Update `MEMORY.md`** with results; design Phase 2 (Fix 1 runner text fallback) or Phase 3 (third family) based on data.

Each step has a verification gate. If step N fails verification, stop and re-evaluate before proceeding. Hard rule: do not skip steps to chase the 85q × N=3 result.

---

## What I expect (so we can compare against reality)

Best case: DS full MV EX 0.529 → 0.65, within-family Δ +0.12, p < 0.05. Gemini holds at 0.659.

Realistic case: DS full MV EX 0.55-0.60, within-family Δ +0.05 to +0.07. Gate fails by a small margin → iterate one more round (refine R1-R7 wording, add 2-3 more few-shot examples).

Worst case: DS gains nothing or regresses. This would mean the per-family prompt isn't the right abstraction layer and we need to look at whether ADK's LiteLlm wrapper is mangling tool schemas in ways the prompt can't fix. At that point, drop down to the LiteLlm tool-call protocol layer.
