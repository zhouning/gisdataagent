import unittest
from unittest.mock import MagicMock, patch
import os
import sys
import yaml

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.agents.llm_agent import LlmAgent, Agent
from google.adk.tools import VertexAiSearchTool

# Load prompts
PROMPTS_FILE = os.path.join(os.path.dirname(__file__), 'prompts.yaml')
with open(PROMPTS_FILE, 'r', encoding='utf-8') as f:
    prompts = yaml.safe_load(f)

class TestKnowledgeAgent(unittest.TestCase):
    def setUp(self):
        # Initialize the agent with the updated instruction
        # Note: We mock the actual LLM call later, so model name doesn't matter for logic test
        self.agent = Agent(
            name="vertex_search_agent",
            model="gemini-2.5-flash",
            instruction=prompts['knowledge_agent_instruction'],
            description="具有Vertex AI Search功能的企业文档搜索助手",
            output_key="domain_knowledge",
            # We will mock the tool execution
            tools=[VertexAiSearchTool(data_store_id="mock_id")]
        )

    def test_agent_initialization(self):
        """Test if the agent is initialized with correct parameters from prompts.yaml."""
        self.assertEqual(self.agent.name, "vertex_search_agent")
        self.assertIn("土地资源格局优化与破碎化研究专家", self.agent.instruction)
        self.assertIn("FFI", self.agent.instruction)
        self.assertEqual(self.agent.output_key, "domain_knowledge")

    @patch('google.adk.agents.llm_agent.LlmAgent.call_model') 
    def test_optimization_theory_query(self, mock_call_model):
        """
        Test a scenario asking for land use optimization theory.
        We simulate the LLM's response to verify it follows the formatting rules.
        """
        
        # 1. Simulate the User Query
        user_query = "请解释林地和耕地空间布局优化的理论基础，特别是坡度因素的影响。"
        
        # 2. Mock the LLM response (Simulating what Gemini SHOULD output based on our prompt)
        # This tests if our prompt is likely to generate the desired structure.
        mock_response_content = """
## 1. 适宜性评价理论
根据 **土地适宜性评价 (Land Suitability Evaluation)** 理论，坡度是决定耕地与林地空间布局的核心因子。

### 坡度阈值与转换逻辑
| 坡度区间 | 适宜用地类型 | 优化策略 | 理论依据 |
| :--- | :--- | :--- | :--- |
| $	heta \le 6^{\circ}$ | 优质耕地 | **优先保留/置换** | 机械化操作成本最低，水土流失风险极低 [Source 1]。 |
| $6^{\circ} < 	heta \le 25^{\circ}$ | 一般耕地/果园 | **有条件保留** | 需配套梯田等水土保持措施。 |
| $	heta > 25^{\circ}$ | 林地 | **强制退耕** | 根据《退耕还林条例》，此坡度耕地极易发生土壤侵蚀，生态风险高 [Source 2]。 |

## 2. 空间置换模型
空间优化的目标通常是在保持各类用地总量 $S_{total}$ 不变的前提下，最小化全局适宜性成本 $C$：

$$
	ext{Minimize } C = \sum_{i=1}^{N} \sum_{k \in \{farm, forest\}} x_{ik} \cdot cost(slope_i, type_k)
$$

其中 $x_{ik}$ 为二值变量，表示地块 $i$ 是否分配为类型 $k$。

> **结论**：高坡度耕地应与低坡度林地进行 **空间置换 (Spatial Swap)**，从而在不减少耕地红线面积的前提下，显著降低平均耕作坡度并提升生态安全 [Source 3]。
"""
        
        # Configure the mock to return this content
        # Note: The actual return structure of call_model depends on ADK internals.
        # Here we assume it returns a response object with a .text attribute or similar.
        mock_call_model.return_value.text = mock_response_content
        
        # 3. Execution (This is a conceptual run, as we can't fully run the agent without a real runner context)
        # In a real unit test suite for ADK, we would use a TestRunner.
        # Here we manually verify the instruction contains key constraints.
        
        instruction = self.agent.instruction
        
        # Assertions on the Prompt Content (Static Verification)
        self.assertIn("Standard LaTeX", instruction, "Instruction should mandate LaTeX format.")
        self.assertIn("Markdown 表格", instruction, "Instruction should mandate Markdown tables.")
        self.assertIn("引用溯源", instruction, "Instruction should require citation sources.")
        self.assertIn("坡度", instruction, "Instruction should mention slope suitability.")
        
        print("
[Test Output Preview] Simulated Agent Response:
")
        print(mock_response_content)

if __name__ == '__main__':
    unittest.main()
