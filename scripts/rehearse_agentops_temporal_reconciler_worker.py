#!/usr/bin/env python3
"""Run the disposable managed AgentOps reconciler worker rehearsal."""

from data_agent.agentops_temporal_reconciler_worker_postgres_rehearsal import (
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())
