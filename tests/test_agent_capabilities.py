import os
import unittest
import json
from skills.registry import SKILL_FUNCTIONS, OLLAMA_TOOLS, execute_tool

class TestAgentCapabilities(unittest.TestCase):
    def test_registered_skills(self):
        registered_names = set(SKILL_FUNCTIONS.keys())
        tool_names = set(tool["function"]["name"] for tool in OLLAMA_TOOLS)

        self.assertEqual(registered_names, tool_names, "Registered functions and Ollama tools definitions must match")

    def test_missing_execution_capability(self):
        registered_names = set(SKILL_FUNCTIONS.keys())
        self.assertIn("run_command_tool", registered_names, "Agent is missing run_command_tool to execute code/commands")

if __name__ == "__main__":
    unittest.main()
