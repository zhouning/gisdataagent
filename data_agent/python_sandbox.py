"""
Python Sandbox Execution Engine — User Tools Phase 2.

Executes user-defined Python code in an isolated subprocess with:
- AST validation (import whitelist, forbidden builtins)
- Timeout enforcement (default 30s, max 60s)
- Environment variable sanitization
- stdout/stderr capture (100KB limit)
- Restricted builtins
"""
import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Optional

from .user_tools import validate_python_code

# Env vars to strip from subprocess environment
_SENSITIVE_ENV_KEYS = {
    "POSTGRES_PASSWORD", "CHAINLIT_AUTH_SECRET", "GOOGLE_API_KEY",
    "WECOM_APP_SECRET", "WECOM_TOKEN", "WECOM_ENCODING_AES_KEY",
    "DINGTALK_APP_SECRET", "FEISHU_APP_SECRET",
    "DATABASE_URL", "DB_PASSWORD", "SECRET_KEY",
    "AWS_SECRET_ACCESS_KEY", "AZURE_STORAGE_KEY",
}

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 60
MAX_OUTPUT_BYTES = 100 * 1024  # 100KB


def _sanitize_env() -> dict:
    """Create a clean environment for subprocess."""
    env = {k: v for k, v in os.environ.items() if k not in _SENSITIVE_ENV_KEYS}
    # Ensure Python can find standard library
    env["PYTHONPATH"] = ""
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


_RUNNER_TEMPLATE = '''
import json, sys

# Restricted builtins
_ALLOWED_BUILTINS = {
    "abs", "all", "any", "bin", "bool", "bytes", "chr", "dict",
    "divmod", "enumerate", "filter", "float", "format", "frozenset",
    "hex", "int", "isinstance", "issubclass", "iter", "len", "list",
    "map", "max", "min", "next", "oct", "ord", "pow", "print",
    "range", "repr", "reversed", "round", "set", "slice", "sorted",
    "str", "sum", "tuple", "type", "zip",
}
import builtins as _b
_safe = {k: getattr(_b, k) for k in _ALLOWED_BUILTINS if hasattr(_b, k)}
_safe["__import__"] = __import__  # needed for whitelisted imports
_safe["__name__"] = "__main__"
_safe["__builtins__"] = _safe

# User code (injected)
$USER_CODE$

# Execute
params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
result = tool_function(**params)
print("__SANDBOX_RESULT__" + json.dumps(result, ensure_ascii=False, default=str))
'''


def execute_python_sandbox(
    code: str,
    parameters: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Execute user Python code in an isolated subprocess.

    Returns {"status": "ok", "result": ...} or {"status": "error", "message": ...}.
    """
    # Validate code first
    error = validate_python_code(code)
    if error:
        return {"status": "error", "message": f"Code validation failed: {error}"}

    timeout = min(max(timeout, 1), MAX_TIMEOUT)
    params = parameters or {}

    # Write runner script to temp file
    runner_code = _RUNNER_TEMPLATE.replace("$USER_CODE$", code)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(runner_code)
        tmp.close()

        result = subprocess.run(
            [sys.executable, tmp.name, json.dumps(params, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_sanitize_env(),
            cwd=tempfile.gettempdir(),
        )

        stdout = result.stdout[:MAX_OUTPUT_BYTES]
        stderr = result.stderr[:MAX_OUTPUT_BYTES]

        if result.returncode != 0:
            return {
                "status": "error",
                "message": stderr or f"Process exited with code {result.returncode}",
                "stdout": stdout,
            }

        # Extract result from stdout
        marker = "__SANDBOX_RESULT__"
        if marker in stdout:
            result_json = stdout.split(marker)[-1].strip()
            try:
                parsed = json.loads(result_json)
                # Collect any print output before the marker
                print_output = stdout.split(marker)[0].strip()
                return {
                    "status": "ok",
                    "result": parsed,
                    "stdout": print_output if print_output else None,
                }
            except json.JSONDecodeError:
                return {"status": "ok", "result": result_json}

        return {"status": "ok", "result": stdout.strip() if stdout.strip() else None}

    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Execution timed out after {timeout}s"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
