import os
import unittest
import json
from unittest.mock import patch

import agents.local_agent as local_agent
import agents.google_adk_agent as google_adk_agent
from skills.registry import SKILL_FUNCTIONS, OLLAMA_TOOLS, execute_tool

class TestAgentCapabilities(unittest.TestCase):
    def test_registered_skills(self):
        registered_names = set(SKILL_FUNCTIONS.keys())
        tool_names = set(tool["function"]["name"] for tool in OLLAMA_TOOLS)

        self.assertEqual(registered_names, tool_names, "Registered functions and Ollama tools definitions must match")

    def test_missing_execution_capability(self):
        registered_names = set(SKILL_FUNCTIONS.keys())
        self.assertIn("run_command_tool", registered_names, "Agent is missing run_command_tool to execute code/commands")

    def test_google_backend_is_optional(self):
        self.assertEqual(google_adk_agent.model_name("gemini:gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertFalse(google_adk_agent.available_model() and not google_adk_agent.is_available())

    def test_ollama_bind_address_is_safe_for_client(self):
        self.assertEqual(
            local_agent._normalize_ollama_host("0.0.0.0:11434"),
            "http://127.0.0.1:11434",
        )

    def test_tool_iteration_guard_persists_across_model_rounds(self):
        tool_call = {
            "function": {
                "name": "list_dir_tool",
                "arguments": {"path": "."},
            }
        }
        response = [{"message": {"tool_calls": [tool_call]}}]

        with patch.object(local_agent, "MAX_TOOL_ITERATIONS", 2), \
                patch.object(local_agent.ollama_client, "chat", side_effect=[response] * 3) as chat, \
                patch.object(local_agent, "execute_tool", return_value='{"success": true}'):
            payloads = list(local_agent.query_local_model_stream([], "test-model"))

        guards = [
            payload for payload in payloads
            if isinstance(payload, dict) and payload.get("type") == "loop_guard"
        ]
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0]["iteration"], 3)
        self.assertEqual(chat.call_count, 3)

if __name__ == "__main__":
    unittest.main()
