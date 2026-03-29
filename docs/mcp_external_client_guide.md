# MCP External Client Setup Guide

The GIS Data Agent supports the Model Context Protocol (MCP) to allow external AI assistants like **Claude Desktop** and **Cursor** to connect and use the platform's advanced spatial analysis and data governance capabilities.

## Architecture

```text
Claude Desktop (Client)
      │
      ▼
   (stdio)
      │
      ▼
mcp_server_stdio.py (Entry point)
      │
      ▼
GIS Data Agent Backend
  ├── Data Catalog & Lineage
  ├── Custom Skills & Toolsets
  ├── Spatial Analysis Pipelines
  └── Workflows
```

## Setup Instructions: Claude Desktop

1. Make sure Claude Desktop is installed on your system.
2. Locate the Claude Desktop configuration file:
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
3. Edit the file to add the GIS Data Agent server:

```json
{
  "mcpServers": {
    "gis-data-agent": {
      "command": "C:/path/to/your/adk/.venv/Scripts/python.exe",
      "args": [
        "C:/path/to/your/adk/data_agent/mcp_server_stdio.py",
        "--user", "admin"
      ],
      "env": {
        "PYTHONPATH": "C:/path/to/your/adk",
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/gis_agent"
      }
    }
  }
}
```

*Note: Replace `C:/path/to/your/adk/` with the actual absolute path to your ADK repository.*

4. Restart Claude Desktop.
5. You should now see the ⚒️ icon indicating that MCP tools are connected.

## Setup Instructions: Cursor IDE

1. Open Cursor Settings > Features > MCP Servers.
2. Click **+ Add New MCP Server**.
3. Fill in the details:
   - **Type**: `command`
   - **Name**: `GIS Data Agent`
   - **Command**: `C:/path/to/your/adk/.venv/Scripts/python.exe C:/path/to/your/adk/data_agent/mcp_server_stdio.py --user admin`
4. Make sure to set environment variables if your script needs them (e.g., in `.env` file).
5. Click **Save** and verify the connection status turns green.

## Available Capabilities via MCP

Once connected, external clients gain access to:
- `search_catalog`: Search for spatial data assets
- `get_data_lineage`: Trace data lineage graphs
- `list_skills` / `list_toolsets`: Discover platform capabilities
- `run_analysis_pipeline`: Execute complex multi-step analysis on the ADK backend
- All built-in geoprocessing and visualization tools exposed by the General pipeline

## Troubleshooting

- **Server fails to start**: Check the Claude Desktop logs. The `mcp_server_stdio.py` writes logs to `stderr` which Claude Desktop captures.
- **Database connection error**: Ensure your PostgreSQL database is running and `DATABASE_URL` is correctly set in your environment.
- **Path not found**: Use absolute paths in the `claude_desktop_config.json`. Windows paths should use forward slashes `/` or escaped backslashes `\\`.