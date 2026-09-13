# AI Agents in Action Assessment and Roadmap Refresh Design

**Date:** 2026-07-11

**Status:** Approved for documentation implementation

## Objective

Convert the completed review of *AI Agents in Action, Second Edition* and the GIS Data Agent runtime audit into two durable project artifacts:

1. A detailed, evidence-backed assessment document.
2. A focused refresh of the main project roadmap.

The refresh must preserve existing product, standards-platform, TWM, and research roadmap history while adding a cross-cutting Agent Runtime Reliability and Cognitive Control workstream.

## Deliverables

### Assessment document

Create `docs/ai-agents-in-action-gis-data-agent-assessment-2026-07-11.md` with:

- reading and audit scope;
- the relevant principles from chapters 4 through 11;
- existing GIS Data Agent strengths;
- an evidence-backed gap matrix with code references;
- a target runtime architecture;
- P0, P1, and P2 implementation priorities;
- measurable acceptance criteria;
- verification results, limitations, and audit boundaries.

The document must distinguish among capabilities that are mature, capabilities that exist but are not wired into the main runtime, and capabilities that need to be added.

### Main roadmap refresh

Modify `docs/roadmap.md` without rewriting historical release sections. The refresh will:

- update the document date and `Next` summary;
- add an `Agent Runtime Reliability & Cognitive Control` workstream near the top;
- link to the assessment document as the evidence basis;
- define P0 work for typed quality loops, unified runner policy, tenant isolation, and task decomposition repair;
- define P1 work for tool-surface reduction, `RunWorkspace`, proactive memory, and evaluation feedback loops;
- define P2 work for observability wiring, MCP capability contracts, and versioned releases;
- attach dependencies and objective acceptance gates to each work package.

Existing TWM, Standards Platform, NL2SQL, and other product roadmap status must remain unchanged.

## Information Architecture

The assessment document is the full source of evidence. The main roadmap is the execution index and must avoid duplicating the complete audit narrative.

```text
Book and code audit
  -> detailed assessment document
  -> prioritized roadmap workstream
  -> future implementation plans and regression gates
```

The target runtime architecture recorded in both documents is:

```text
FrontDoor (small meta-tool set)
  -> RunWorkspace
  -> deterministic AttentionRouter
  -> typed specialist workers
  -> typed evaluator
  -> retry | replan | retrieve memory | respond | escalate
```

## Evidence Rules

- Code findings must use repository-relative file paths and line-oriented references where practical.
- Claims about book content must identify the relevant chapter and printed summary page.
- Tool-count claims must report that they were measured by runtime enumeration.
- Test results must name the command scope and must not be presented as proof of untested runtime semantics.
- The document must explicitly state that no external Gemini, PostGIS, or remote MCP end-to-end run was performed during this audit.

## Verification

After editing:

1. Check both Markdown files for placeholders and broken relative links.
2. Confirm the roadmap contains exactly one new cross-cutting runtime workstream.
3. Confirm historical roadmap status text is not unintentionally changed.
4. Review `git diff --check` and the scoped diff for the three documentation files.
5. Report that no application code was modified.

