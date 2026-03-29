#!/usr/bin/env python3
"""
MCP Stdio Server Entry Point
Exposes GIS Data Agent tools over MCP stdio transport for external clients like Claude Desktop.
"""
import sys
import os
import asyncio
import logging
import argparse

# Ensure data_agent is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.mcp_hub import get_mcp_hub
from data_agent.user_context import current_user_id, current_user_role
from mcp.server.stdio import stdio_server

# Set up logging to stderr (stdout is used for MCP)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("mcp_stdio")

async def main():
    parser = argparse.ArgumentParser(description="GIS Data Agent MCP Server (Stdio)")
    parser.add_argument("--user", default="admin", help="User context to run as")
    parser.add_argument("--role", default="admin", help="Role context")
    args = parser.parse_args()

    # Get MCP Hub
    hub = get_mcp_hub()

    # 1. Connect configured MCP servers in the background
    logger.info(f"Starting MCP Hub for user {args.user}")
    await hub.startup()

    # Create the FastMCP server instance
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("GIS Data Agent", dependencies=["pandas", "geopandas"])

    # 2. Get all tools from General pipeline
    # To expose GIS tools to the external agent
    logger.info("Registering tools from General pipeline...")
    tools = await hub.get_all_tools(pipeline="general", username=args.user)

    for tool in tools:
        # Wrap ADK tools for FastMCP
        # Simplified wrapper for standard execution
        def make_handler(adk_tool):
            def handler(**kwargs):
                try:
                    # Set user context
                    current_user_id.set(args.user)
                    current_user_role.set(args.role)
                    return adk_tool(**kwargs)
                except Exception as e:
                    logger.error(f"Error executing {adk_tool.name}: {e}")
                    return f"Error: {str(e)}"
            return handler

        handler = make_handler(tool)
        handler.__name__ = tool.name
        handler.__doc__ = tool.description

        # Add tool to MCP server
        mcp.add_tool(handler)
        logger.info(f"Registered tool: {tool.name}")

    logger.info("Starting stdio server loop...")

    # 3. Run the stdio server
    options = mcp._mcp_server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await mcp._mcp_server.run(
            read_stream,
            write_stream,
            options,
            raise_exceptions=True
        )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
