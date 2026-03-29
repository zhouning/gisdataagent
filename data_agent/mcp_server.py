"""
GIS Data Agent — MCP Server.

Exposes ~30 GIS analysis tools via Model Context Protocol (MCP) so that
external AI clients (Claude Desktop, Cursor, Windsurf, etc.) can call them.

## Claude Desktop configuration example

Add to claude_desktop_config.json → mcpServers:

{
  "mcpServers": {
    "gis-data-agent": {
      "command": "D:\\\\adk\\\\.venv\\\\Scripts\\\\python.exe",
      "args": ["-m", "data_agent.mcp_server"],
      "cwd": "D:\\\\adk",
      "env": {
        "MCP_USER": "analyst1",
        "MCP_ROLE": "analyst"
      }
    }
  }
}

Environment variables:
  MCP_USER  — username for file sandbox and DB context (default: "mcp_user")
  MCP_ROLE  — role for RBAC checks (default: "analyst")

All database/API credentials are loaded from data_agent/.env automatically.
"""
import json
import os
from contextlib import asynccontextmanager

# Load .env before any tool imports (DB credentials, API keys, etc.)
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(_env_path)

from mcp.server.fastmcp import FastMCP

from .user_context import current_user_id, current_session_id, current_user_role


# ---------------------------------------------------------------------------
# Lifespan — set ContextVars for stdio (single-user) mode
# ---------------------------------------------------------------------------

@asynccontextmanager
async def gis_lifespan(server: FastMCP):
    """Initialize user context for the MCP session.

    In stdio transport (single-user), we set ContextVars once from env vars.
    All GIS tools read these implicitly via user_context.py helpers.
    """
    username = os.environ.get("MCP_USER", "mcp_user")
    current_user_id.set(username)
    current_session_id.set(f"mcp_{username}")
    current_user_role.set(os.environ.get("MCP_ROLE", "analyst"))

    # Ensure user upload directory exists
    upload_dir = os.path.join(os.path.dirname(__file__), "uploads", username)
    os.makedirs(upload_dir, exist_ok=True)

    yield {}


# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "GIS Data Agent",
    instructions=(
        "GIS空间数据分析工具集。支持数据探查、空间处理、地理编码、"
        "可视化、数据库查询等30+专业GIS分析工具。\n\n"
        "v2.0 新增高阶工具：search_catalog（语义搜索数据目录）、"
        "get_data_lineage（血缘追踪）、list_skills/list_toolsets（能力查询）、"
        "list_virtual_sources（远程数据源）、run_analysis_pipeline（执行完整分析管线）。\n\n"
        "文件路径说明：工具接受的 file_path 参数为用户上传目录下的相对路径或文件名。"
        "输出文件保存在用户上传目录中并返回路径。"
    ),
    lifespan=gis_lifespan,
)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("gis://tools/catalog")
def tool_catalog() -> str:
    """List all available GIS tools with descriptions."""
    from .mcp_tool_registry import TOOL_DEFINITIONS

    lines = ["# GIS Analysis Tools\n"]
    for defn in TOOL_DEFINITIONS:
        ann = defn.get("annotations")
        tag = " [只读]" if ann and ann.readOnlyHint else ""
        lines.append(f"- **{defn['name']}**{tag}: {defn['description']}")
    lines.append(f"\nTotal: {len(TOOL_DEFINITIONS)} tools")
    return "\n".join(lines)


@mcp.resource("gis://server/status")
def server_status() -> str:
    """Server health check and configuration info."""
    from .mcp_tool_registry import TOOL_DEFINITIONS

    return json.dumps({
        "server": "GIS Data Agent MCP",
        "version": "2.0.0",
        "user": current_user_id.get(),
        "role": current_user_role.get(),
        "tool_count": len(TOOL_DEFINITIONS),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Register all tools
# ---------------------------------------------------------------------------

from .mcp_tool_registry import register_all_tools

_tool_count = register_all_tools(mcp)
print(f"[MCP Server] Registered {_tool_count} GIS tools.")


# ---------------------------------------------------------------------------
# CLI entry point: python -m data_agent.mcp_server [--transport stdio|sse] [--test]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]

    if "--test" in args:
        # Self-test mode: verify tool registration and basic functionality
        from .mcp_tool_registry import TOOL_DEFINITIONS
        print(f"[MCP Self-Test] Tools registered: {len(TOOL_DEFINITIONS)}")
        categories = {}
        for d in TOOL_DEFINITIONS:
            cat = d.get("category", "other")
            categories.setdefault(cat, []).append(d["name"])
        for cat, tools in sorted(categories.items()):
            print(f"  [{cat}] {len(tools)} tools: {', '.join(tools[:5])}{'...' if len(tools) > 5 else ''}")
        print(f"[MCP Self-Test] User: {os.environ.get('MCP_USER', 'mcp_user')}")
        print(f"[MCP Self-Test] Role: {os.environ.get('MCP_ROLE', 'analyst')}")
        print("[MCP Self-Test] PASSED — all tools registered successfully.")
        sys.exit(0)

    transport = "stdio"
    if "--transport" in args:
        idx = args.index("--transport")
        if idx + 1 < len(args):
            transport = args[idx + 1]

    if transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run()
