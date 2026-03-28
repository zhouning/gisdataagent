"""
Prompt Registry - Version control for built-in agent prompts.
Extends prompts/__init__.py with DB-backed versioning.
Falls back to YAML when DB unavailable.
"""
from sqlalchemy import text
from .db_engine import get_engine
from .observability import get_logger

logger = get_logger("prompt_registry")


class PromptRegistry:
    """Manages prompt versions with environment isolation"""

    def get_prompt(self, domain: str, prompt_key: str, env: str = "prod") -> str:
        """Get prompt with environment awareness. Priority: DB → YAML fallback"""
        engine = get_engine()
        if engine:
            try:
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT prompt_text FROM agent_prompt_versions
                        WHERE domain = :domain
                          AND prompt_key = :key
                          AND environment = :env
                          AND is_active = true
                        LIMIT 1
                    """), {"domain": domain, "key": prompt_key, "env": env})
                    row = result.fetchone()
                    if row:
                        logger.debug(f"Loaded prompt {domain}.{prompt_key} from DB ({env})")
                        return row[0]
            except Exception as e:
                logger.warning(f"DB prompt load failed, falling back to YAML: {e}")

        # Fallback to YAML
        from . import prompts
        return prompts.load_prompts(domain)[prompt_key]

    def create_version(self, domain: str, prompt_key: str, prompt_text: str,
                       env: str = "dev", change_reason: str = "",
                       created_by: str = "system") -> int:
        """Create new version, auto-increment version number"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COALESCE(MAX(version), 0) + 1
                FROM agent_prompt_versions
                WHERE domain = :domain AND prompt_key = :key AND environment = :env
            """), {"domain": domain, "key": prompt_key, "env": env})
            next_version = result.scalar()

            result = conn.execute(text("""
                INSERT INTO agent_prompt_versions
                (domain, prompt_key, version, environment, prompt_text, change_reason, created_by)
                VALUES (:domain, :key, :ver, :env, :text, :reason, :by)
                RETURNING id
            """), {
                "domain": domain, "key": prompt_key, "ver": next_version,
                "env": env, "text": prompt_text, "reason": change_reason, "by": created_by
            })
            conn.commit()
            version_id = result.scalar()
            logger.info(f"Created prompt version {domain}.{prompt_key} v{next_version} ({env})")
            return version_id

    def deploy(self, version_id: int, target_env: str) -> dict:
        """Deploy version to target environment"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT domain, prompt_key, version, prompt_text
                FROM agent_prompt_versions WHERE id = :id
            """), {"id": version_id})
            row = result.fetchone()
            if not row:
                raise ValueError(f"Version {version_id} not found")

            domain, prompt_key, version, prompt_text = row

            conn.execute(text("""
                UPDATE agent_prompt_versions
                SET is_active = false
                WHERE domain = :domain AND prompt_key = :key
                  AND environment = :env AND is_active = true
            """), {"domain": domain, "key": prompt_key, "env": target_env})

            result = conn.execute(text("""
                SELECT id FROM agent_prompt_versions
                WHERE domain = :domain AND prompt_key = :key
                  AND environment = :env AND version = :ver
            """), {"domain": domain, "key": prompt_key, "env": target_env, "ver": version})
            existing = result.fetchone()

            if existing:
                conn.execute(text("""
                    UPDATE agent_prompt_versions
                    SET is_active = true, deployed_at = NOW()
                    WHERE id = :id
                """), {"id": existing[0]})
                new_id = existing[0]
            else:
                result = conn.execute(text("""
                    INSERT INTO agent_prompt_versions
                    (domain, prompt_key, version, environment, prompt_text, is_active, deployed_at)
                    VALUES (:domain, :key, :ver, :env, :text, true, NOW())
                    RETURNING id
                """), {
                    "domain": domain, "key": prompt_key, "ver": version,
                    "env": target_env, "text": prompt_text
                })
                new_id = result.scalar()

            conn.commit()
            logger.info(f"Deployed {domain}.{prompt_key} v{version} to {target_env}")
            return {"version_id": new_id, "environment": target_env}

    def rollback(self, domain: str, prompt_key: str, env: str = "prod") -> str:
        """Rollback to previous version"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, version FROM agent_prompt_versions
                WHERE domain = :domain AND prompt_key = :key AND environment = :env
                  AND is_active = false
                ORDER BY version DESC LIMIT 1
            """), {"domain": domain, "key": prompt_key, "env": env})
            row = result.fetchone()
            if not row:
                raise ValueError(f"No previous version found for {domain}.{prompt_key} in {env}")

            prev_id, prev_version = row

            conn.execute(text("""
                UPDATE agent_prompt_versions
                SET is_active = false
                WHERE domain = :domain AND prompt_key = :key
                  AND environment = :env AND is_active = true
            """), {"domain": domain, "key": prompt_key, "env": env})

            conn.execute(text("""
                UPDATE agent_prompt_versions
                SET is_active = true, deployed_at = NOW()
                WHERE id = :id
            """), {"id": prev_id})

            conn.commit()
            logger.info(f"Rolled back {domain}.{prompt_key} to v{prev_version} in {env}")
            return f"v{prev_version}"
