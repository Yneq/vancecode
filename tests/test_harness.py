import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vancecode.agent import Agent
from vancecode.cli import main, load_env
from vancecode.provider import OpenAICompatibleProvider, ProviderError
from vancecode.safety import Safety
from vancecode.tools import Tools
from scripts.offline_demo import run_demo


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.tools = Tools(Safety(self.root, lambda action: True))
        (self.root / "code.py").write_text("value = 1\n")

    def test_repair_failure_feedback_retry_success(self):
        self.assertTrue(run_demo().success)

    def test_traversal_absolute_and_symlink_escape(self):
        for path in ("../secret", str(self.root / "code.py")):
            self.assertFalse(self.tools.execute("read_file", {"path": path})["ok"])
        (self.root / "escape").symlink_to(self.root.parent)
        self.assertFalse(self.tools.execute("read_file", {"path": "escape/secret"})["ok"])

    def test_protected_files_and_tests(self):
        (self.root / ".env").write_text("SECRET=hidden")
        (self.root / "tests").mkdir()
        (self.root / "tests/test_a.py").write_text("value = 1")
        self.assertFalse(self.tools.execute("read_file", {"path": ".env"})["ok"])
        self.assertFalse(self.tools.execute("apply_patch", {"path": "tests/test_a.py", "old": "1", "new": "2"})["ok"])
        self.assertNotIn("hidden", json.dumps(self.tools.execute("search_code", {"query": ""})))

    def test_invalid_arguments_and_unknown_tool(self):
        for name, args in [("shell", {}), ("run_tests", {"command": "echo bad"}),
                           ("read_file", {"path": 4}), ("read_file", [])]:
            self.assertFalse(self.tools.execute(name, args)["ok"])

    def test_edit_invalidates_verification_and_stale_patch_fails(self):
        self.tools.verified_revision = 0
        self.assertTrue(self.tools.execute("apply_patch", {"path": "code.py", "old": "1", "new": "2"})["ok"])
        self.assertNotEqual(self.tools.revision, self.tools.verified_revision)
        self.assertFalse(self.tools.execute("apply_patch", {"path": "code.py", "old": "1", "new": "3"})["ok"])

    def test_denied_edit_does_not_change_file(self):
        tools = Tools(Safety(self.root, lambda action: False))
        self.assertFalse(tools.execute("apply_patch", {"path": "code.py", "old": "1", "new": "2"})["ok"])
        self.assertEqual((self.root / "code.py").read_text(), "value = 1\n")

    def test_empty_suite_cannot_pass(self):
        (self.root / "tests").mkdir()
        self.assertFalse(self.tools.execute("run_tests", {})["passed"])

    def test_same_size_same_timestamp_edit_does_not_reuse_stale_bytecode(self):
        import py_compile
        source = self.root / "code.py"
        source.write_text("value = 1\n")
        timestamp = source.stat().st_mtime
        py_compile.compile(str(source), doraise=True)
        source.write_text("value = 2\n")
        os.utime(source, (timestamp, timestamp))
        (self.root / "tests").mkdir()
        (self.root / "tests/test_value.py").write_text(
            "import unittest\nfrom code import value\nclass T(unittest.TestCase):\n"
            " def test_new_value(self): self.assertEqual(value, 2)\n")
        self.assertTrue(self.tools.execute("run_tests", {})["passed"])

    def test_timeout(self):
        (self.root / "tests").mkdir()
        (self.root / "tests/test_wait.py").write_text("import time\ntime.sleep(10)\n")
        self.tools.timeout = 0.1
        self.assertTrue(self.tools.execute("run_tests", {})["timed_out"])

    def test_test_process_does_not_receive_api_key(self):
        (self.root / "tests").mkdir()
        (self.root / "tests/test_env.py").write_text(
            "import os, unittest\nclass T(unittest.TestCase):\n"
            " def test_env(self): self.assertNotIn('OPENAI_API_KEY', os.environ)\n")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}):
            self.assertTrue(self.tools.execute("run_tests", {})["passed"])

    def test_model_cannot_claim_success_without_tests(self):
        class Premature:
            def complete(self, messages, tools):
                return {"role": "assistant", "content": "done"}
        result = Agent(Premature(), self.tools, max_steps=2).run("fix bug")
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "step_limit")
        self.assertEqual(Agent(Premature(), self.tools, max_context_chars=1).run("fix").reason, "context_limit")

    def test_provider_wire_contract(self):
        from io import BytesIO
        provider = OpenAICompatibleProvider("secret", "test-model")
        response = {"choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "tool_calls": [{"id": "a", "type": "function",
            "function": {"name": "run_tests", "arguments": "{}"}}]}}]}
        with patch("vancecode.provider.urlopen", return_value=BytesIO(json.dumps(response).encode())) as send:
            result = provider.complete([{"role": "user", "content": "fix"}], [])
        request = send.call_args.args[0]
        self.assertEqual(json.loads(request.data)["model"], "test-model")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(result["tool_calls"][0]["id"], "a")

    def test_provider_malformed_response(self):
        from io import BytesIO
        with patch("vancecode.provider.urlopen", return_value=BytesIO(b'{}')):
            with self.assertRaises(ProviderError):
                OpenAICompatibleProvider("key", "model").complete([], [])

    def test_env_preserves_existing_values(self):
        env = self.root / "config"
        env.write_text("VANCECODE_MODEL=from-file\n")
        with patch.dict(os.environ, {"VANCECODE_MODEL": "existing"}):
            load_env(env)
            self.assertEqual(os.environ["VANCECODE_MODEL"], "existing")

    def test_cli_missing_configuration_returns_two(self):
        with patch.dict(os.environ, {}, clear=True), patch("vancecode.cli.load_env"):
            self.assertEqual(main(["fix", "--repo", str(self.root)]), 2)
