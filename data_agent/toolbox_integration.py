import os
from google.adk.tools import ToolboxToolset

def get_database_tools():
    """
    Initializes and returns the Database MCP Toolbox tools.
    Requires MCP_TOOLBOX_URL to be set in environment variables.
    """
    server_url = os.environ.get("MCP_TOOLBOX_URL", "http://localhost:8080")
    
    # We load the 'database' toolset which typically includes:
    # - query_database
    # - list_tables
    # - describe_table
    # - etc.
    try:
        # Note: The toolset name might vary based on server config. 
        # 'database' is a common convention for the SQL toolset.
        # We can also load specific tools if needed.
        toolbox = ToolboxToolset(
            server_url=server_url,
            toolset_name="database" 
        )
        return toolbox
    except Exception as e:
        print(f"Warning: Failed to initialize MCP Toolbox at {server_url}: {e}")
        return None
