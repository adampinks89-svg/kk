import os
import unittest
import json
import tempfile
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

    def test_agent_writes_before_and_after_switching_workspace(self):
        """Agent może zapisać pliki kolejno w workspace i po zmianie cwd."""
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as drive_d:
            responses = [
                [{"message": {"tool_calls": [{
                    "function": {
                        "name": "write_file_tool",
                        "arguments": {"path": "hello.txt", "content": "hello Fervv"},
                    }
                }]}}],
                [{"message": {"tool_calls": [{
                    "function": {
                        "name": "run_command_tool",
                        "arguments": {"command": "cd D:/"},
                    }
                }]}}],
                [{"message": {"tool_calls": [{
                    "function": {
                        "name": "write_file_tool",
                        "arguments": {"path": "hello2.txt", "content": "hello Fervv 2"},
                    }
                }]}}],
                [{"message": {"content": "Gotowe"}}],
            ]

            def execute_tool_side_effect(name, args):
                if name == "write_file_tool":
                    path = args["path"]
                    with open(path, "w", encoding="utf-8") as file:
                        file.write(args["content"])
                    return json.dumps({"success": True, "path": path})
                if name == "run_command_tool":
                    return json.dumps({
                        "success": True,
                        "returncode": 0,
                        "stdout": "",
                        "stderr": "",
                        "cwd": drive_d,
                    })
                raise AssertionError(f"Nieoczekiwane narzędzie: {name}")

            with patch.object(local_agent.ollama_client, "chat", side_effect=responses), \
                    patch.object(local_agent, "execute_tool", side_effect=execute_tool_side_effect):
                list(local_agent.query_local_model_stream([], "test-model", working_directory=workspace))

            with open(os.path.join(workspace, "hello.txt"), encoding="utf-8") as file:
                self.assertEqual(file.read(), "hello Fervv")
            with open(os.path.join(drive_d, "hello2.txt"), encoding="utf-8") as file:
                self.assertEqual(file.read(), "hello Fervv 2")

if __name__ == "__main__":
    unittest.main()
