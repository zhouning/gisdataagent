"""
Chainlit Data Layer — table setup and URL helper.

Creates the 5 PascalCase tables expected by Chainlit's built-in
``ChainlitDataLayer`` (asyncpg-based) so that chat threads, steps,
elements, and feedback persist across page refreshes.

The ADK ``DatabaseSessionService`` (which stores agent state / events)
uses its own tables and is independent of these.
"""

from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import get_db_connection_url

# ---------------------------------------------------------------------------
# DDL — Chainlit PascalCase tables
# ---------------------------------------------------------------------------

CHAINLIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS "User" (
    id TEXT PRIMARY KEY,
    identifier TEXT UNIQUE NOT NULL,
    metadata JSONB DEFAULT '{}',
    "createdAt" TIMESTAMP DEFAULT NOW(),
    "updatedAt" TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS "Thread" (
    id TEXT PRIMARY KEY,
    name TEXT,
    "userId" TEXT REFERENCES "User"(id) ON DELETE SET NULL,
    "userIdentifier" TEXT,
    metadata JSONB DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    "createdAt" TIMESTAMP DEFAULT NOW(),
    "updatedAt" TIMESTAMP DEFAULT NOW(),
    "deletedAt" TIMESTAMP
);

CREATE TABLE IF NOT EXISTS "Step" (
    id TEXT PRIMARY KEY,
    "threadId" TEXT REFERENCES "Thread"(id) ON DELETE CASCADE,
    "parentId" TEXT,
    name TEXT,
    type TEXT,
    input TEXT,
    output TEXT,
    metadata JSONB DEFAULT '{}',
    "isError" BOOLEAN DEFAULT FALSE,
    "disableFeedback" BOOLEAN DEFAULT FALSE,
    "createdAt" TIMESTAMP DEFAULT NOW(),
    "startTime" TIMESTAMP,
    "endTime" TIMESTAMP,
    generation JSONB,
    "showInput" TEXT,
    language TEXT
);

CREATE TABLE IF NOT EXISTS "Element" (
    id TEXT PRIMARY KEY,
    "threadId" TEXT REFERENCES "Thread"(id) ON DELETE CASCADE,
    "stepId" TEXT,
    metadata JSONB DEFAULT '{}',
    mime TEXT,
    name TEXT,
    "objectKey" TEXT,
    url TEXT,
    "chainlitKey" TEXT,
    display TEXT,
    size TEXT,
    language TEXT,
    page INTEGER,
    props JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS "Feedback" (
    id TEXT PRIMARY KEY,
    "stepId" TEXT REFERENCES "Step"(id) ON DELETE CASCADE,
    name TEXT,
    value REAL,
    comment TEXT,
    "createdAt" TIMESTAMP DEFAULT NOW()
);
"""


def ensure_chainlit_tables():
    """Create Chainlit data layer tables if they don't exist.

    Uses the shared SQLAlchemy engine from ``db_engine.get_engine()``.
    Non-fatal: prints a warning and returns if the database is not
    configured or the DDL fails.
    """
    engine = get_engine()
    if not engine:
        print("[Session] WARNING: Database not configured. "
              "Chat thread persistence disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(CHAINLIT_SCHEMA_SQL))
            # Migrate: add deletedAt column if missing (Chainlit 2.9+)
            conn.execute(text("""
                ALTER TABLE "Thread" ADD COLUMN IF NOT EXISTS "deletedAt" TIMESTAMP
            """))
            conn.commit()
        print("[Session] Chainlit data layer tables ready.")
    except Exception as e:
        print(f"[Session] WARNING: Failed to create Chainlit tables: {e}")


def get_chainlit_db_url() -> str | None:
    """Return the raw PostgreSQL URL for Chainlit's asyncpg-based data layer.

    The ``ChainlitDataLayer`` uses ``asyncpg.create_pool()`` directly,
    which expects a plain ``postgresql://`` URL (not SQLAlchemy async).
    Returns ``None`` if database credentials are not configured.
    """
    return get_db_connection_url()
