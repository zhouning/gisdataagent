"""Team collaboration toolset: create, manage teams and shared resources."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..team_manager import (
    create_team,
    list_my_teams,
    invite_to_team,
    remove_from_team,
    list_team_members,
    list_team_resources,
    leave_team,
    delete_team,
)

_ALL_FUNCS = [
    create_team,
    list_my_teams,
    invite_to_team,
    remove_from_team,
    list_team_members,
    list_team_resources,
    leave_team,
    delete_team,
]


class TeamToolset(BaseToolset):
    """Team collaboration and resource sharing tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
