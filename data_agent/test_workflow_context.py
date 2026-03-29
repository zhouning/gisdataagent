"""Test workflow step context continuity (TD-005 fix)."""
import asyncio
import unittest
from unittest.mock import patch, MagicMock
from data_agent.workflow_engine import execute_workflow


class TestWorkflowContextInjection(unittest.TestCase):
    """Test that step N receives context from step N-1."""

    def test_workflow_step_context_injection(self):
        """Test that step N receives context from step N-1."""

        # Mock workflow data
        workflow_data = {
            "id": 1,
            "workflow_name": "test_workflow",
            "owner_username": "test_user",
            "steps": [
                {"step_id": "step1", "pipeline_type": "general", "prompt": "分析数据", "label": "数据分析"},
                {"step_id": "step2", "pipeline_type": "governance", "prompt": "生成报告", "label": "报告生成"},
            ],
            "parameters": {},
            "sla_total_seconds": None,
        }

        # Mock database for run record
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = [123]  # run_id

        # Track prompts sent to each step
        prompts_received = []

        async def mock_run_pipeline(agent, session_service, user_id, session_id, prompt, **kwargs):
            prompts_received.append(prompt)
            result = MagicMock()
            result.error = None
            result.duration_seconds = 1.0
            result.total_input_tokens = 100
            result.total_output_tokens = 50
            result.generated_files = ["output.shp"]
            result.report_text = f"步骤完成: 发现3个问题"
            return result

        with patch("data_agent.workflow_engine.get_engine", return_value=mock_engine), \
             patch("data_agent.workflow_engine.get_workflow", return_value=workflow_data), \
             patch("data_agent.pipeline_runner.run_pipeline_headless", side_effect=mock_run_pipeline), \
             patch("data_agent.workflow_engine._get_agent_for_pipeline", return_value=MagicMock()):

            result = asyncio.run(execute_workflow(workflow_id=1, param_overrides={}))

            # Verify step 1 received original prompt
            self.assertIn("分析数据", prompts_received[0])
            self.assertNotIn("[上一步结果]", prompts_received[0])

            # Verify step 2 received injected context from step 1
            self.assertIn("生成报告", prompts_received[1])
            self.assertIn("[上一步结果]", prompts_received[1])
            self.assertIn("步骤 1", prompts_received[1])
            self.assertIn("数据分析", prompts_received[1])
            self.assertIn("发现3个问题", prompts_received[1])

            self.assertEqual(result["status"], "completed")
            self.assertEqual(len(result["step_results"]), 2)
