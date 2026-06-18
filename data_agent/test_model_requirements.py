"""Tests for model runtime environment requirements."""

import unittest


class TestModelRequirements(unittest.TestCase):
    def test_local_ollama_model_does_not_require_google_cloud_project(self):
        from data_agent.model_requirements import model_requires_google_cloud_project

        self.assertFalse(
            model_requires_google_cloud_project(
                "gemma4-26b-ollama",
                env={"GOOGLE_GENAI_USE_VERTEXAI": "TRUE"},
            )
        )

    def test_gemma_google_model_does_not_require_vertex_project(self):
        from data_agent.model_requirements import model_requires_google_cloud_project

        self.assertFalse(
            model_requires_google_cloud_project(
                "gemma-4-31b-it",
                env={"GOOGLE_GENAI_USE_VERTEXAI": "TRUE"},
            )
        )

    def test_vertex_gemini_model_requires_google_cloud_project(self):
        from data_agent.model_requirements import model_requires_google_cloud_project

        self.assertTrue(
            model_requires_google_cloud_project(
                "gemini-2.5-flash",
                env={"GOOGLE_GENAI_USE_VERTEXAI": "TRUE"},
            )
        )

    def test_ai_studio_gemini_model_does_not_require_google_cloud_project(self):
        from data_agent.model_requirements import model_requires_google_cloud_project

        self.assertFalse(
            model_requires_google_cloud_project(
                "gemini-2.5-flash",
                env={"GOOGLE_GENAI_USE_VERTEXAI": "FALSE"},
            )
        )

    def test_configured_local_models_do_not_require_google_cloud_project(self):
        from data_agent.model_requirements import configured_models_require_google_cloud_project

        self.assertFalse(
            configured_models_require_google_cloud_project(
                env={"GOOGLE_GENAI_USE_VERTEXAI": "TRUE"},
                model_names=[
                    "gemma4-26b-ollama",
                    "gemma4-26b-ollama",
                    "gemma4-26b-ollama",
                    "gemma4-26b-ollama",
                ],
            )
        )


if __name__ == "__main__":
    unittest.main()
