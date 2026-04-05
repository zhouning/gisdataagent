"""
Test agent topology API endpoint.
"""
import pytest
from unittest.mock import Mock, patch


def test_topology_endpoint_structure():
    """Test that topology endpoint returns correct structure."""
    from data_agent.api.topology_routes import _api_agent_topology

    # Mock request
    request = Mock()

    # Mock the agent imports at the source they are imported from
    with patch('data_agent.agent.data_pipeline') as mock_dp, \
         patch('data_agent.agent.governance_pipeline') as mock_gp, \
         patch('data_agent.agent.general_pipeline') as mock_gen:

        # Setup mock agents
        mock_dp.name = 'data_pipeline'
        mock_dp.__class__.__name__ = 'SequentialAgent'
        mock_dp.tools = []
        mock_dp.sub_agents = []

        mock_gp.name = 'governance_pipeline'
        mock_gp.__class__.__name__ = 'SequentialAgent'
        mock_gp.tools = []
        mock_gp.sub_agents = []

        mock_gen.name = 'general_pipeline'
        mock_gen.__class__.__name__ = 'SequentialAgent'
        mock_gen.tools = []
        mock_gen.sub_agents = []

        # Call endpoint
        import asyncio
        response = asyncio.run(_api_agent_topology(request))

        # Verify response structure
        assert response.status_code == 200
        import json
        data = json.loads(response.body)

        assert 'agents' in data
        assert 'toolsets' in data
        assert 'pipelines' in data
        assert len(data['agents']) == 3
        assert len(data['pipelines']) == 3


def test_topology_extracts_tools():
    """Test that topology extracts toolset information."""
    from data_agent.api.topology_routes import _extract_toolset_info

    # Mock toolset with public callable methods (not _tools list)
    class MockToolset:
        """Mock toolset for testing."""
        def tool1(self):
            pass

        def tool2(self):
            pass

        def tool3(self):
            pass

    toolset = MockToolset()
    info = _extract_toolset_info(toolset)

    assert info['name'] == 'MockToolset'
    assert info['tool_count'] == 3
    assert 'Mock toolset' in info['description']
