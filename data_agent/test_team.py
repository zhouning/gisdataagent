"""Tests for team collaboration (F4) and parallel ingestion (F3)."""
import unittest
from unittest.mock import patch, MagicMock
import asyncio


# ---------------------------------------------------------------------------
# F3: Pipeline structural tests (v9.0.2 — ParallelDataIngestion in DataEngineering)
# ---------------------------------------------------------------------------

class TestPipelineStructure(unittest.TestCase):
    """Verify optimization pipeline structure after v9.0.2 parallel ingestion."""

    def test_data_pipeline_is_sequential(self):
        from google.adk.agents import SequentialAgent
        from data_agent.agent import data_pipeline
        self.assertIsInstance(data_pipeline, SequentialAgent)

    def test_pipeline_has_four_stages(self):
        from data_agent.agent import data_pipeline
        self.assertEqual(len(data_pipeline.sub_agents), 4)

    def test_knowledge_tool_replaces_parallel(self):
        """knowledge_agent is now an AgentTool, not a parallel peer."""
        from google.adk.tools import AgentTool
        from data_agent.agent import knowledge_tool
        self.assertIsInstance(knowledge_tool, AgentTool)

    def test_parallel_data_ingestion_in_pipeline(self):
        """DataEngineering should contain ParallelDataIngestion."""
        from google.adk.agents import ParallelAgent
        from data_agent.agent import data_pipeline
        data_eng = data_pipeline.sub_agents[0]
        self.assertEqual(data_eng.name, "DataEngineering")
        parallel = data_eng.sub_agents[0]
        self.assertIsInstance(parallel, ParallelAgent)
        self.assertEqual(parallel.name, "ParallelDataIngestion")


# ---------------------------------------------------------------------------
# F4: TeamToolset tests
# ---------------------------------------------------------------------------

class TestTeamToolset(unittest.TestCase):
    """Verify TeamToolset returns expected tools."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_toolset_all_tools(self):
        from data_agent.toolsets.team_tools import TeamToolset
        ts = TeamToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("create_team", names)
        self.assertIn("list_my_teams", names)
        self.assertIn("invite_to_team", names)
        self.assertIn("remove_from_team", names)
        self.assertIn("list_team_members", names)
        self.assertIn("list_team_resources", names)
        self.assertIn("leave_team", names)
        self.assertIn("delete_team", names)
        self.assertEqual(len(tools), 8)

    def test_toolset_with_filter(self):
        from data_agent.toolsets.team_tools import TeamToolset
        ts = TeamToolset(tool_filter=["create_team", "list_my_teams"])
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 2)
        names = {t.name for t in tools}
        self.assertEqual(names, {"create_team", "list_my_teams"})


# ---------------------------------------------------------------------------
# F4: team_manager function tests (mocked DB)
# ---------------------------------------------------------------------------

def _mock_engine_with_data(rows=None, rowcount=1):
    """Create a mock engine that returns predictable results."""
    engine = MagicMock()
    conn = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows or []
    result.fetchone.return_value = (1, "testuser") if rows is None else (rows[0] if rows else None)
    result.rowcount = rowcount
    conn.execute.return_value = result
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = conn
    return engine, conn


class TestCreateTeam(unittest.TestCase):

    @patch("data_agent.team_manager.record_audit")
    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_role", new_callable=MagicMock)
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_create_team_success(self, mock_uid, mock_role, mock_engine, mock_inject, mock_audit):
        mock_uid.get.return_value = "admin"
        mock_role.get.return_value = "analyst"
        engine, conn = _mock_engine_with_data()
        # fetchone for getting team id
        conn.execute.return_value.fetchone.return_value = (42,)
        mock_engine.return_value = engine
        from data_agent.team_manager import create_team
        result = create_team("GIS分析组", "测试团队")
        self.assertEqual(result["status"], "success")
        self.assertIn("GIS分析组", result["message"])

    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_role", new_callable=MagicMock)
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_create_team_viewer_blocked(self, mock_uid, mock_role, mock_engine):
        mock_uid.get.return_value = "viewer1"
        mock_role.get.return_value = "viewer"
        from data_agent.team_manager import create_team
        result = create_team("MyTeam")
        self.assertEqual(result["status"], "error")
        self.assertIn("查看者", result["message"])

    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_role", new_callable=MagicMock)
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_create_team_no_db(self, mock_uid, mock_role, mock_engine):
        mock_uid.get.return_value = "admin"
        mock_role.get.return_value = "analyst"
        mock_engine.return_value = None
        from data_agent.team_manager import create_team
        result = create_team("NoDBTeam")
        self.assertEqual(result["status"], "error")
        self.assertIn("数据库", result["message"])

    @patch("data_agent.team_manager.current_user_role", new_callable=MagicMock)
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_create_team_name_too_short(self, mock_uid, mock_role):
        mock_uid.get.return_value = "admin"
        mock_role.get.return_value = "analyst"
        from data_agent.team_manager import create_team
        result = create_team("X")
        self.assertEqual(result["status"], "error")


class TestListMyTeams(unittest.TestCase):

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_list_teams_with_data(self, mock_uid, mock_engine, mock_inject):
        mock_uid.get.return_value = "user1"
        engine, conn = _mock_engine_with_data(rows=[
            ("GIS组", "user1", "测试", "owner", 3),
            ("分析组", "user2", "分析团队", "member", 5),
        ])
        mock_engine.return_value = engine
        from data_agent.team_manager import list_my_teams
        result = list_my_teams()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["count"], 2)
        self.assertTrue(result["teams"][0]["is_owner"])

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_list_teams_empty(self, mock_uid, mock_engine, mock_inject):
        mock_uid.get.return_value = "user1"
        engine, conn = _mock_engine_with_data(rows=[])
        mock_engine.return_value = engine
        from data_agent.team_manager import list_my_teams
        result = list_my_teams()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["count"], 0)

    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_list_teams_no_db(self, mock_uid, mock_engine):
        mock_uid.get.return_value = "user1"
        mock_engine.return_value = None
        from data_agent.team_manager import list_my_teams
        result = list_my_teams()
        self.assertEqual(result["status"], "error")


class TestInviteToTeam(unittest.TestCase):

    @patch("data_agent.team_manager.record_audit")
    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_invite_success(self, mock_uid, mock_engine, mock_inject, mock_audit):
        mock_uid.get.return_value = "owner1"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            # _is_team_admin short-circuits (owner1 == owner1), no DB call
            elif call_count[0] == 2:  # count members
                result.fetchone.return_value = (3,)
            elif call_count[0] == 3:  # max_members
                result.fetchone.return_value = (10,)
            else:
                result.fetchone.return_value = None
                result.rowcount = 1
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import invite_to_team
        result = invite_to_team("GIS组", "analyst1", "member")
        self.assertEqual(result["status"], "success")

    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_invite_invalid_role(self, mock_uid):
        mock_uid.get.return_value = "owner1"
        from data_agent.team_manager import invite_to_team
        result = invite_to_team("GIS组", "user1", "superadmin")
        self.assertEqual(result["status"], "error")
        self.assertIn("无效角色", result["message"])

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_invite_not_owner(self, mock_uid, mock_engine, mock_inject):
        mock_uid.get.return_value = "member1"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            elif call_count[0] == 2:  # _get_member_role
                result.fetchone.return_value = ("member",)
            else:
                result.fetchone.return_value = None
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import invite_to_team
        result = invite_to_team("GIS组", "analyst1", "member")
        self.assertEqual(result["status"], "error")
        self.assertIn("所有者或管理员", result["message"])


class TestRemoveFromTeam(unittest.TestCase):

    @patch("data_agent.team_manager.record_audit")
    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_remove_success(self, mock_uid, mock_engine, mock_inject, mock_audit):
        mock_uid.get.return_value = "owner1"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            elif call_count[0] == 2:  # _is_team_admin -> _get_member_role
                result.fetchone.return_value = ("owner",)
            else:
                result.rowcount = 1
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import remove_from_team
        result = remove_from_team("GIS组", "member1")
        self.assertEqual(result["status"], "success")

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_remove_owner_blocked(self, mock_uid, mock_engine, mock_inject):
        mock_uid.get.return_value = "owner1"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            else:
                result.fetchone.return_value = None
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import remove_from_team
        result = remove_from_team("GIS组", "owner1")
        self.assertEqual(result["status"], "error")
        self.assertIn("所有者", result["message"])

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_remove_not_admin(self, mock_uid, mock_engine, mock_inject):
        mock_uid.get.return_value = "member1"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = (1, "owner1")
            elif call_count[0] == 2:
                result.fetchone.return_value = ("member",)
            else:
                result.fetchone.return_value = None
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import remove_from_team
        result = remove_from_team("GIS组", "other_user")
        self.assertEqual(result["status"], "error")


class TestListTeamMembers(unittest.TestCase):

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_role", new_callable=MagicMock)
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_list_members_success(self, mock_uid, mock_role, mock_engine, mock_inject):
        mock_uid.get.return_value = "user1"
        mock_role.get.return_value = "analyst"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            elif call_count[0] == 2:  # _get_member_role
                result.fetchone.return_value = ("member",)
            elif call_count[0] == 3:  # list members
                result.fetchall.return_value = [
                    ("owner1", "owner", "2025-01-01"),
                    ("user1", "member", "2025-01-02"),
                ]
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import list_team_members
        result = list_team_members("GIS组")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["count"], 2)

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_role", new_callable=MagicMock)
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_list_members_not_in_team(self, mock_uid, mock_role, mock_engine, mock_inject):
        mock_uid.get.return_value = "outsider"
        mock_role.get.return_value = "analyst"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            elif call_count[0] == 2:  # _get_member_role
                result.fetchone.return_value = None  # not a member
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import list_team_members
        result = list_team_members("GIS组")
        self.assertEqual(result["status"], "error")
        self.assertIn("不是该团队成员", result["message"])


class TestLeaveTeam(unittest.TestCase):

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_leave_success(self, mock_uid, mock_engine, mock_inject):
        mock_uid.get.return_value = "member1"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            else:
                result.rowcount = 1
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import leave_team
        result = leave_team("GIS组")
        self.assertEqual(result["status"], "success")

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_owner_cannot_leave(self, mock_uid, mock_engine, mock_inject):
        mock_uid.get.return_value = "owner1"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import leave_team
        result = leave_team("GIS组")
        self.assertEqual(result["status"], "error")
        self.assertIn("所有者", result["message"])


class TestDeleteTeam(unittest.TestCase):

    @patch("data_agent.team_manager.record_audit")
    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_role", new_callable=MagicMock)
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_delete_success(self, mock_uid, mock_role, mock_engine, mock_inject, mock_audit):
        mock_uid.get.return_value = "owner1"
        mock_role.get.return_value = "analyst"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import delete_team
        result = delete_team("GIS组")
        self.assertEqual(result["status"], "success")

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_role", new_callable=MagicMock)
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_delete_not_owner(self, mock_uid, mock_role, mock_engine, mock_inject):
        mock_uid.get.return_value = "member1"
        mock_role.get.return_value = "analyst"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import delete_team
        result = delete_team("GIS组")
        self.assertEqual(result["status"], "error")
        self.assertIn("所有者", result["message"])


class TestListTeamResources(unittest.TestCase):

    @patch("data_agent.team_manager._inject_user_context")
    @patch("data_agent.team_manager.get_engine")
    @patch("data_agent.team_manager.current_user_role", new_callable=MagicMock)
    @patch("data_agent.team_manager.current_user_id", new_callable=MagicMock)
    def test_list_resources_all(self, mock_uid, mock_role, mock_engine, mock_inject):
        mock_uid.get.return_value = "user1"
        mock_role.get.return_value = "analyst"
        engine, conn = _mock_engine_with_data()
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # _get_team_id
                result.fetchone.return_value = (1, "owner1")
            elif call_count[0] == 2:  # _get_member_role
                result.fetchone.return_value = ("member",)
            elif call_count[0] == 3:  # team member list
                result.fetchall.return_value = [("user1",), ("user2",)]
            elif call_count[0] == 4:  # tables
                result.fetchall.return_value = [("tbl1", "user1", True, "test table")]
            elif call_count[0] == 5:  # templates
                result.fetchall.return_value = [
                    (1, "模板A", "user2", "general", "测试"),
                ]
            elif call_count[0] == 6:  # memories
                result.fetchall.return_value = []
            else:
                result.fetchall.return_value = []
            return result
        conn.execute.side_effect = side_effect
        mock_engine.return_value = engine
        from data_agent.team_manager import list_team_resources
        result = list_team_resources("GIS组", "all")
        self.assertEqual(result["status"], "success")
        self.assertIn("tables", result["resources"])
        self.assertIn("templates", result["resources"])
        self.assertIn("memories", result["resources"])

    def test_invalid_resource_type(self):
        from data_agent.team_manager import list_team_resources
        result = list_team_resources("GIS组", "invalid")
        self.assertEqual(result["status"], "error")


class TestBackwardCompatTeamImports(unittest.TestCase):
    """Verify TeamToolset is properly exported."""

    def test_toolset_import_from_init(self):
        from data_agent.toolsets import TeamToolset
        self.assertIsNotNone(TeamToolset)

    def test_team_tools_in_agents(self):
        """Verify TeamToolset is registered in GeneralProcessing."""
        from data_agent.agent import general_processing_agent
        from data_agent.toolsets.team_tools import TeamToolset

        gp_toolsets = [type(t) for t in general_processing_agent.tools if isinstance(t, TeamToolset)]
        self.assertEqual(len(gp_toolsets), 1)


if __name__ == "__main__":
    unittest.main()
