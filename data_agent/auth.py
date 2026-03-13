"""
Authentication module for GIS Data Agent.
Supports password login and Google OAuth2.
"""
import os
import re
import hashlib
import secrets
from typing import Optional
from sqlalchemy import text
import chainlit as cl

from .db_engine import get_engine
from .database_tools import T_APP_USERS
from .i18n import t


def _hash_password(password: str, salt: str = None) -> tuple:
    """Hash password using PBKDF2-HMAC-SHA256. Returns (hash_hex, salt_hex)."""
    if salt is None:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return pw_hash.hex(), salt


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash. Format: salt$hash"""
    try:
        salt, hash_hex = stored_hash.split('$')
        computed_hash, _ = _hash_password(password, salt)
        return secrets.compare_digest(computed_hash, hash_hex)
    except (ValueError, AttributeError):
        return False


def _make_password_hash(password: str) -> str:
    """Create storable password hash string. Format: salt$hash"""
    hash_hex, salt = _hash_password(password)
    return f"{salt}${hash_hex}"


def ensure_users_table():
    """Create the app_users table if it doesn't exist, and seed admin user."""
    engine = get_engine()
    if not engine:
        print("[Auth] WARNING: Database not configured. Auth will use fallback mode.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_APP_USERS} (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(500),
                    display_name VARCHAR(200),
                    email VARCHAR(255) DEFAULT '',
                    role VARCHAR(20) DEFAULT 'analyst',
                    auth_provider VARCHAR(20) DEFAULT 'password',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()

            # Seed admin if no users exist
            result = conn.execute(text(f"SELECT COUNT(*) FROM {T_APP_USERS}"))
            count = result.scalar()
            if count == 0:
                admin_hash = _make_password_hash("admin123")
                conn.execute(text(
                    f"INSERT INTO {T_APP_USERS} (username, password_hash, display_name, role) "
                    "VALUES (:u, :p, :d, :r)"
                ), {"u": "admin", "p": admin_hash, "d": "Administrator", "r": "admin"})
                conn.commit()
                print("[Auth] Seeded default admin user (admin / admin123). Please change password.")

        print("[Auth] Users table ready.")
    except Exception as e:
        print(f"[Auth] Error initializing users table: {e}")


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Verify credentials against database. Returns user dict or None."""
    engine = get_engine()
    if not engine:
        # Fallback: accept admin/admin123 without DB
        if username == "admin" and password == "admin123":
            return {"username": "admin", "display_name": "Admin (Offline)", "role": "admin"}
        return None

    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"SELECT username, password_hash, display_name, role FROM {T_APP_USERS} WHERE username = :u"
            ), {"u": username})
            row = result.fetchone()
            if row and _verify_password(password, row[1]):
                return {
                    "username": row[0],
                    "display_name": row[2] or row[0],
                    "role": row[3] or "analyst"
                }
    except Exception as e:
        print(f"[Auth] Error during authentication: {e}")
    return None


def register_user(username: str, password: str, display_name: str = "",
                   email: str = "") -> dict:
    """Register a new user with 'analyst' role.

    Returns: {"status": "success", "message": "..."} or {"status": "error", "message": "..."}
    """
    # --- Input Validation ---
    if not username or not password:
        return {"status": "error", "message": t("auth.username_empty")}

    if not re.match(r'^[a-zA-Z0-9_]{3,30}$', username):
        return {"status": "error", "message": t("auth.username_format")}

    if len(password) < 8:
        return {"status": "error", "message": t("auth.password_length")}
    if not re.search(r'[a-zA-Z]', password) or not re.search(r'\d', password):
        return {"status": "error", "message": t("auth.password_complexity")}

    if email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return {"status": "error", "message": t("auth.email_format")}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": t("auth.db_unavailable")}

    try:
        with engine.connect() as conn:
            # Check duplicate
            exists = conn.execute(text(
                f"SELECT 1 FROM {T_APP_USERS} WHERE username = :u"
            ), {"u": username}).fetchone()
            if exists:
                return {"status": "error", "message": t("auth.username_exists")}

            # Insert new user
            pw_hash = _make_password_hash(password)
            conn.execute(text(
                f"INSERT INTO {T_APP_USERS} "
                "(username, password_hash, display_name, email, role, auth_provider) "
                "VALUES (:u, :p, :d, :e, 'analyst', 'password')"
            ), {"u": username, "p": pw_hash, "d": display_name or username,
                "e": email or ""})
            conn.commit()
            return {"status": "success", "message": t("auth.register_success")}
    except Exception as e:
        return {"status": "error", "message": t("auth.register_failed", error=str(e))}


def delete_user_account(username: str, confirm_password: str) -> dict:
    """
    Delete a user account with password confirmation.
    Cascades: removes user data from token_usage, memories, share_links,
    team_members, audit_log, data_catalog, annotations, and app_users.
    Also removes user upload directory.

    Admins cannot delete themselves via this method.

    Args:
        username: The user to delete.
        confirm_password: Password for verification.

    Returns:
        {"status": "success"|"error", "message": str}
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": t("auth.delete_db_unavailable")}

    # Verify password first
    user = authenticate_user(username, confirm_password)
    if not user:
        return {"status": "error", "message": t("auth.delete_password_failed")}

    if user.get("role") == "admin":
        return {"status": "error", "message": t("auth.delete_admin_blocked")}

    try:
        with engine.connect() as conn:
            # Cascade delete related data
            cascade_tables = [
                ("agent_token_usage", "username"),
                ("agent_user_memories", "username"),
                ("agent_share_links", "owner_username"),
                ("agent_team_members", "username"),
                ("agent_audit_log", "username"),
                ("agent_map_annotations", "username"),
                ("agent_knowledge_bases", "owner_username"),
            ]
            for table, col in cascade_tables:
                try:
                    conn.execute(text(f"DELETE FROM {table} WHERE {col} = :u"), {"u": username})
                except Exception:
                    pass  # Table may not exist

            # Delete user account
            result = conn.execute(text(
                f"DELETE FROM {T_APP_USERS} WHERE username = :u"
            ), {"u": username})
            conn.commit()

            if result.rowcount == 0:
                return {"status": "error", "message": t("auth.delete_user_not_found")}

        # Remove upload directory
        import shutil
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads", username)
        if os.path.exists(upload_dir):
            shutil.rmtree(upload_dir, ignore_errors=True)

        return {"status": "success", "message": t("auth.delete_success")}
    except Exception as e:
        return {"status": "error", "message": t("auth.delete_failed", error=str(e))}


def ensure_wecom_user(wecom_userid: str) -> dict:
    """
    Ensure a WeChat Enterprise user exists in app_users.
    Auto-creates as analyst if not found. Username: wx_{wecom_userid}.

    Returns: {"username": "wx_{...}", "display_name": "...", "role": "analyst"}
    """
    username = f"wx_{wecom_userid}"
    engine = get_engine()

    if not engine:
        return {"username": username, "display_name": username, "role": "analyst"}

    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"SELECT username, display_name, role FROM {T_APP_USERS} WHERE username = :u"
            ), {"u": username})
            row = result.fetchone()

            if row:
                return {
                    "username": row[0],
                    "display_name": row[1] or row[0],
                    "role": row[2] or "analyst",
                }

            # Auto-create: random password (never used for WeCom login)
            pw_hash = _make_password_hash(secrets.token_hex(16))
            conn.execute(text(
                f"INSERT INTO {T_APP_USERS} "
                "(username, password_hash, display_name, role, auth_provider) "
                "VALUES (:u, :p, :d, 'analyst', 'wecom')"
            ), {"u": username, "p": pw_hash, "d": f"WeCom:{wecom_userid}"})
            conn.commit()
            print(f"[Auth] Created WeCom user: {username}")
            return {"username": username, "display_name": f"WeCom:{wecom_userid}", "role": "analyst"}
    except Exception as e:
        print(f"[Auth] Error ensuring WeCom user: {e}")
        return {"username": username, "display_name": username, "role": "analyst"}


def upsert_oauth_user(email: str, display_name: str, provider: str) -> dict:
    """Create or update an OAuth user on first login. Returns user dict."""
    engine = get_engine()
    user = {"username": email, "display_name": display_name or email, "role": "analyst"}

    if not engine:
        return user


def ensure_bot_user(bot_user_id: str, platform: str) -> dict:
    """
    Ensure a bot platform user exists in app_users.
    Auto-creates as analyst if not found. Username: {prefix}_{bot_user_id}.

    Args:
        bot_user_id: Platform-specific user identifier.
        platform: Platform name (e.g., 'dingtalk', 'feishu', 'wecom').

    Returns: {"username": "{prefix}_{...}", "display_name": "...", "role": "analyst"}
    """
    prefix_map = {"wecom": "wx", "dingtalk": "dt", "feishu": "fs"}
    prefix = prefix_map.get(platform, platform[:2])
    username = f"{prefix}_{bot_user_id}"
    engine = get_engine()

    if not engine:
        return {"username": username, "display_name": username, "role": "analyst"}

    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"SELECT username, display_name, role FROM {T_APP_USERS} WHERE username = :u"
            ), {"u": username})
            row = result.fetchone()

            if row:
                return {
                    "username": row[0],
                    "display_name": row[1] or row[0],
                    "role": row[2] or "analyst",
                }

            # Auto-create: random password (never used for bot login)
            pw_hash = _make_password_hash(secrets.token_hex(16))
            display = f"{platform.title()}:{bot_user_id}"
            conn.execute(text(
                f"INSERT INTO {T_APP_USERS} "
                "(username, password_hash, display_name, role, auth_provider) "
                "VALUES (:u, :p, :d, 'analyst', :provider)"
            ), {"u": username, "p": pw_hash, "d": display, "provider": platform})
            conn.commit()
            print(f"[Auth] Created {platform} user: {username}")
            return {"username": username, "display_name": display, "role": "analyst"}
    except Exception as e:
        print(f"[Auth] Error ensuring {platform} user: {e}")
        return {"username": username, "display_name": username, "role": "analyst"}

    try:
        with engine.connect() as conn:
            # Check if user exists
            result = conn.execute(text(
                f"SELECT username, display_name, role FROM {T_APP_USERS} WHERE username = :u"
            ), {"u": email})
            row = result.fetchone()

            if row:
                user["display_name"] = row[1] or display_name
                user["role"] = row[2] or "analyst"
            else:
                # Auto-create on first OAuth login
                conn.execute(text(
                    f"INSERT INTO {T_APP_USERS} (username, display_name, role, auth_provider) "
                    "VALUES (:u, :d, :r, :p)"
                ), {"u": email, "d": display_name, "r": "analyst", "p": provider})
                conn.commit()
                print(f"[Auth] Created new OAuth user: {email} ({provider})")
    except Exception as e:
        print(f"[Auth] Error upserting OAuth user: {e}")

    return user


# --- Chainlit Auth Callbacks ---

@cl.password_auth_callback
async def password_auth_callback(username: str, password: str) -> Optional[cl.User]:
    """Chainlit password login handler."""
    user = authenticate_user(username, password)
    if user:
        try:
            from .audit_logger import record_audit, ACTION_LOGIN_SUCCESS
            record_audit(user["username"], ACTION_LOGIN_SUCCESS,
                         details={"provider": "password"})
        except Exception:
            pass
        try:
            from .observability import auth_events
            auth_events.labels(event_type="login_success").inc()
        except Exception:
            pass
        return cl.User(
            identifier=user["username"],
            display_name=user["display_name"],
            metadata={"role": user["role"], "provider": "password"}
        )
    try:
        from .audit_logger import record_audit, ACTION_LOGIN_FAILURE
        record_audit(username, ACTION_LOGIN_FAILURE, status="failure",
                     details={"provider": "password"})
    except Exception:
        pass
    try:
        from .observability import auth_events
        auth_events.labels(event_type="login_failure").inc()
    except Exception:
        pass
    return None


# Only register OAuth callback if at least one provider is configured
_oauth_configured = any(
    os.environ.get(k) for k in [
        "OAUTH_GOOGLE_CLIENT_ID",
        "OAUTH_GITHUB_CLIENT_ID",
    ]
)

if _oauth_configured:
    @cl.oauth_callback
    async def oauth_callback(provider_id: str, token: str, raw_user_data: dict,
                             default_app_user: cl.User, id_token: Optional[str] = None) -> Optional[cl.User]:
        """Chainlit OAuth login handler (Google, GitHub, etc.)."""
        email = raw_user_data.get("email", "")
        name = raw_user_data.get("name", raw_user_data.get("login", ""))

        if not email:
            return None

        user = upsert_oauth_user(email, name, provider_id)
        return cl.User(
            identifier=user["username"],
            display_name=user["display_name"],
            metadata={"role": user["role"], "provider": provider_id}
        )
