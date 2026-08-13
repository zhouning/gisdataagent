# AR-0 Staging Mainline Delivery

## Why AR-0 Stayed Blocked

The bottleneck was delivery flow, not absence of implementation:

- remote `main` last advanced on 2026-07-30 while platform work continued on
  chained branches and local worktrees;
- more than 30 open pull requests were based on one another instead of `main`,
  so later evidence could not independently land or run from the protected branch;
- the active worktree accumulated 1,132 modified/deleted paths and 1,493
  untracked paths across unrelated domains;
- staging work was verified inside that accumulated environment. A clean
  `origin/main` worktree exposed a missing runtime dependency:
  `staging_platform_preflight` launches `staging_platform_snapshot`, but the
  original nine-file release-source inventory did not include it.

Repeatedly adding local contracts improved safety but did not reduce the
mainline blocker. The corrective action is to make this bundle the only active
AR-0 delivery until it lands.

## Review Unit

This branch contains only:

- four protected staging workflows: candidate, provenance, deploy, and golden;
- ten protected runtime/verifier sources plus the readiness collector;
- focused contract and source-closure tests.

The source-closure tests fail when a protected staging module imports or
launches another `data_agent.staging_*` module that is absent from the reviewed
bundle.

It does not create a GitHub environment or runner, read or write Kubernetes,
trigger a workflow, or authorize production promotion.

## Merge Gate

Before merge to protected `main`:

1. In a clean worktree based on current `origin/main`, create an isolated
   environment and install `requirements.txt`, matching the existing CI
   dependency path. The default branch does not currently track `uv.lock`, so
   a `--frozen` claim is not valid until lockfile ownership is decided in a
   separate review.
2. Run the focused staging test suite and source-closure tests.
3. Parse all four workflow YAML files, run Ruff, Python compile, and
   `git diff --check`.
4. Require review of the complete workflow/source bundle; do not split the
   YAML from its verifier and renderer sources.

WIP limit: no new chained AR-1/AR-2 platform pull request and no new Agent,
GWM, UI, or unrelated platform slice until this review unit is merged or
explicitly rejected with an owner and reason.

## Post-Merge Responsibility Gate

After merge, responsibilities are sequential:

1. Repository owner confirms readiness reports workflow/source parity on
   `main` and manually runs the candidate publisher.
2. Environment owner creates protected `staging-live`, configures required
   variable/secret names, and provisions the least-privilege deploy and
   observer identities.
3. Runner owner provides an online self-hosted Linux runner labelled
   `gda-staging`.
4. Platform/SRE runs candidate -> provenance -> deploy observation.
5. Data product owner runs the frozen governed post-rollout `PlatformRun` and
   submits its explicit Run ID to golden verification.

AR-0 remains `in_progress` and production promotion remains forbidden until
the live artifact chain and the other roadmap exit conditions are satisfied.
