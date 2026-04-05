"""Tests for NL2Workflow — generating executable workflow DAGs from natural language."""
import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _make_workflow_json(**overrides):
    """Build a valid workflow JSON string for mock LLM responses."""
    wf = {
        "workflow_name": "test-workflow",
        "description": "A test workflow",
        "steps": [
            {
                "step_id": "step_1",
                "label": "Data Profiling",
                "pipeline_type": "custom_skill",
                "skill_name": "data-profiling",
                "prompt": "Profile the dataset",
                "depends_on": [],
            },
            {
                "step_id": "step_2",
                "label": "Topology Check",
                "pipeline_type": "governance",
                "prompt": "Check topology",
                "depends_on": ["step_1"],
            },
        ],
        "parameters": {},
    }
    wf.update(overrides)
    return json.dumps(wf)


# ---------------------------------------------------------------------------
# Core generation tests
# ---------------------------------------------------------------------------


class TestGenerateWorkflow:
    """Tests for the generate_workflow() function."""

    @patch("data_agent.nl2workflow._call_llm")
    def test_simple_two_step_workflow(self, mock_llm):
        mock_llm.return_value = _make_workflow_json()
        from data_agent.nl2workflow import generate_workflow
        result = _run(generate_workflow("Profile data then check topology"))
        assert result["workflow_name"] == "test-workflow"
        assert len(result["steps"]) == 2
        assert result["steps"][0]["step_id"] == "step_1"
        assert result["steps"][1]["depends_on"] == ["step_1"]

    @patch("data_agent.nl2workflow._call_llm")
    def test_parallel_steps(self, mock_llm):
        wf = {
            "workflow_name": "parallel-test",
            "description": "Parallel branches",
            "steps": [
                {"step_id": "step_1", "label": "A", "pipeline_type": "general",
                 "prompt": "Step A", "depends_on": []},
                {"step_id": "step_2", "label": "B", "pipeline_type": "general",
                 "prompt": "Step B", "depends_on": []},
                {"step_id": "step_3", "label": "Merge", "pipeline_type": "general",
                 "prompt": "Merge A and B", "depends_on": ["step_1", "step_2"]},
            ],
            "parameters": {},
        }
        mock_llm.return_value = json.dumps(wf)
        from data_agent.nl2workflow import generate_workflow
        result = _run(generate_workflow("Run A and B in parallel, then merge"))
        assert len(result["steps"]) == 3
        assert result["steps"][2]["depends_on"] == ["step_1", "step_2"]

    @patch("data_agent.nl2workflow._call_llm")
    def test_custom_skill_with_skill_name(self, mock_llm):
        mock_llm.return_value = _make_workflow_json()
        from data_agent.nl2workflow import generate_workflow
        result = _run(generate_workflow("Profile dataset"))
        skill_step = result["steps"][0]
        assert skill_step["pipeline_type"] == "custom_skill"
        assert skill_step["skill_name"] == "data-profiling"

    @patch("data_agent.nl2workflow._call_llm")
    def test_markdown_code_fence_stripped(self, mock_llm):
        raw = "```json\n" + _make_workflow_json() + "\n```"
        mock_llm.return_value = raw
        from data_agent.nl2workflow import generate_workflow
        result = _run(generate_workflow("Some description"))
        assert result["workflow_name"] == "test-workflow"

    @patch("data_agent.nl2workflow._call_llm")
    def test_explanation_populated(self, mock_llm):
        mock_llm.return_value = _make_workflow_json()
        from data_agent.nl2workflow import generate_workflow
        result = _run(generate_workflow("Profile then check"))
        assert "_explanation" in result
        assert "2-step" in result["_explanation"]

    @patch("data_agent.nl2workflow._call_llm")
    def test_missing_workflow_name_gets_default(self, mock_llm):
        wf = {
            "steps": [
                {"step_id": "step_1", "label": "A", "pipeline_type": "general",
                 "prompt": "Do something", "depends_on": []},
            ],
            "parameters": {},
        }
        mock_llm.return_value = json.dumps(wf)
        from data_agent.nl2workflow import generate_workflow
        result = _run(generate_workflow("Do something"))
        assert result["workflow_name"] == "nl-generated-workflow"


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for workflow validation logic."""

    def test_missing_steps_key(self):
        from data_agent.nl2workflow import validate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="'steps' list"):
            validate_workflow({"workflow_name": "x"})

    def test_empty_steps(self):
        from data_agent.nl2workflow import validate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="at least one step"):
            validate_workflow({"steps": []})

    def test_missing_required_field(self):
        from data_agent.nl2workflow import validate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="missing required field"):
            validate_workflow({
                "steps": [{"step_id": "step_1", "label": "A", "pipeline_type": "general"}]
            })

    def test_invalid_pipeline_type(self):
        from data_agent.nl2workflow import validate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="invalid pipeline_type"):
            validate_workflow({
                "steps": [
                    {"step_id": "step_1", "label": "A",
                     "pipeline_type": "invalid_type",
                     "prompt": "Do X", "depends_on": []},
                ]
            })

    def test_custom_skill_missing_skill_name(self):
        from data_agent.nl2workflow import validate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="missing 'skill_name'"):
            validate_workflow({
                "steps": [
                    {"step_id": "step_1", "label": "A",
                     "pipeline_type": "custom_skill",
                     "prompt": "Do X", "depends_on": []},
                ]
            })

    def test_duplicate_step_id(self):
        from data_agent.nl2workflow import validate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="Duplicate step_id"):
            validate_workflow({
                "steps": [
                    {"step_id": "step_1", "label": "A", "pipeline_type": "general",
                     "prompt": "Do A", "depends_on": []},
                    {"step_id": "step_1", "label": "B", "pipeline_type": "general",
                     "prompt": "Do B", "depends_on": []},
                ]
            })

    def test_unknown_dependency(self):
        from data_agent.nl2workflow import validate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="unknown step"):
            validate_workflow({
                "steps": [
                    {"step_id": "step_1", "label": "A", "pipeline_type": "general",
                     "prompt": "Do A", "depends_on": ["step_99"]},
                ]
            })

    def test_circular_dependency(self):
        from data_agent.nl2workflow import validate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="Circular dependency"):
            validate_workflow({
                "steps": [
                    {"step_id": "step_1", "label": "A", "pipeline_type": "general",
                     "prompt": "Do A", "depends_on": ["step_2"]},
                    {"step_id": "step_2", "label": "B", "pipeline_type": "general",
                     "prompt": "Do B", "depends_on": ["step_1"]},
                ]
            })

    def test_self_dependency_cycle(self):
        from data_agent.nl2workflow import validate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="Circular dependency"):
            validate_workflow({
                "steps": [
                    {"step_id": "step_1", "label": "A", "pipeline_type": "general",
                     "prompt": "Do A", "depends_on": ["step_1"]},
                ]
            })

    def test_valid_workflow_passes(self):
        from data_agent.nl2workflow import validate_workflow
        # Should not raise
        validate_workflow({
            "steps": [
                {"step_id": "step_1", "label": "A", "pipeline_type": "general",
                 "prompt": "Do A", "depends_on": []},
                {"step_id": "step_2", "label": "B", "pipeline_type": "governance",
                 "prompt": "Do B", "depends_on": ["step_1"]},
            ]
        })

    @patch("data_agent.nl2workflow._call_llm")
    def test_invalid_json_from_llm(self, mock_llm):
        mock_llm.return_value = "This is not valid JSON at all"
        from data_agent.nl2workflow import generate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="invalid JSON"):
            _run(generate_workflow("Some description"))

    @patch("data_agent.nl2workflow._call_llm")
    def test_empty_description_rejected(self, mock_llm):
        from data_agent.nl2workflow import generate_workflow, WorkflowValidationError
        with pytest.raises(WorkflowValidationError, match="empty"):
            _run(generate_workflow(""))
        mock_llm.assert_not_called()


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------

class TestWorkflowGenerateEndpoint:
    """Tests for POST /api/workflows/generate endpoint."""

    def _make_request(self, body: dict, authenticated: bool = True):
        """Build a mock Starlette Request."""
        from unittest.mock import AsyncMock
        request = MagicMock()
        request.json = AsyncMock(return_value=body)
        request.cookies = {}
        return request

    @patch("data_agent.nl2workflow._call_llm")
    @patch("data_agent.api.workflow_routes._set_user_context", return_value=("testuser", "analyst"))
    @patch("data_agent.api.workflow_routes._get_user_from_request")
    def test_generate_endpoint_success(self, mock_auth, mock_ctx, mock_llm):
        mock_auth.return_value = MagicMock()
        mock_llm.return_value = _make_workflow_json()

        from data_agent.api.workflow_routes import workflow_generate
        req = self._make_request({"description": "Profile then check topology"})
        resp = _run(workflow_generate(req))
        assert resp.status_code == 201
        data = json.loads(resp.body.decode())
        assert "workflow" in data
        assert "explanation" in data
        assert data["workflow"]["workflow_name"] == "test-workflow"

    @patch("data_agent.api.workflow_routes._get_user_from_request", return_value=None)
    def test_generate_endpoint_unauthorized(self, mock_auth):
        from data_agent.api.workflow_routes import workflow_generate
        req = self._make_request({"description": "anything"})
        resp = _run(workflow_generate(req))
        assert resp.status_code == 401

    @patch("data_agent.api.workflow_routes._set_user_context", return_value=("testuser", "analyst"))
    @patch("data_agent.api.workflow_routes._get_user_from_request")
    def test_generate_endpoint_missing_description(self, mock_auth, mock_ctx):
        mock_auth.return_value = MagicMock()
        from data_agent.api.workflow_routes import workflow_generate
        req = self._make_request({"description": ""})
        resp = _run(workflow_generate(req))
        assert resp.status_code == 400

    @patch("data_agent.nl2workflow._call_llm")
    @patch("data_agent.workflow_engine.get_engine")
    @patch("data_agent.api.workflow_routes._set_user_context", return_value=("testuser", "analyst"))
    @patch("data_agent.api.workflow_routes._get_user_from_request")
    def test_generate_endpoint_auto_save(self, mock_auth, mock_ctx, mock_engine, mock_llm):
        mock_auth.return_value = MagicMock()
        mock_llm.return_value = _make_workflow_json()

        # Mock create_workflow to return a fake ID
        with patch("data_agent.workflow_engine.create_workflow", return_value=42) as mock_create:
            from data_agent.api.workflow_routes import workflow_generate
            req = self._make_request({"description": "Profile then check", "auto_save": True})
            resp = _run(workflow_generate(req))
            assert resp.status_code == 201
            data = json.loads(resp.body.decode())
            assert data["saved_id"] == 42

    @patch("data_agent.nl2workflow._call_llm")
    @patch("data_agent.api.workflow_routes._set_user_context", return_value=("testuser", "analyst"))
    @patch("data_agent.api.workflow_routes._get_user_from_request")
    def test_generate_endpoint_validation_error(self, mock_auth, mock_ctx, mock_llm):
        mock_auth.return_value = MagicMock()
        mock_llm.return_value = "not json"

        from data_agent.api.workflow_routes import workflow_generate
        req = self._make_request({"description": "Some workflow"})
        resp = _run(workflow_generate(req))
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Prompt construction test
# ---------------------------------------------------------------------------

class TestPromptConstruction:
    """Tests for the LLM prompt building."""

    def test_prompt_contains_pipeline_types(self):
        from data_agent.nl2workflow import _build_prompt
        prompt = _build_prompt("test description")
        assert "general" in prompt
        assert "governance" in prompt
        assert "optimization" in prompt
        assert "custom_skill" in prompt

    def test_prompt_contains_skills(self):
        from data_agent.nl2workflow import _build_prompt
        prompt = _build_prompt("test description")
        assert "data-profiling" in prompt
        assert "topology-validation" in prompt
        assert "site-selection" in prompt

    def test_prompt_embeds_user_description(self):
        from data_agent.nl2workflow import _build_prompt
        prompt = _build_prompt("My special workflow request")
        assert "My special workflow request" in prompt
