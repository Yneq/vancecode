from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vancecode.benchmarks import BENCHMARKS, Benchmark
from vancecode.evaluation import evaluate, main, ScriptedBenchmarkProvider, write_report
from vancecode.provider import ProviderError
from vancecode.tools import Tools


class EvaluationTests(unittest.TestCase):
    def test_all_cases_repeat_with_fresh_repo_and_independent_grading(self):
        report = evaluate(ScriptedBenchmarkProvider, mode="offline-scripted", repeats=2)
        self.assertEqual(report["summary"]["runs"], 6)
        self.assertEqual(report["summary"]["passed"], 6)
        self.assertEqual(report["summary"]["success_rate"], 1)
        self.assertEqual(report["mode"], "offline-scripted")
        for row in report["runs"]:
            self.assertTrue(row["baseline_failed"])
            self.assertTrue(row["final_tests_passed"])
            self.assertEqual(row["reason"], "verified_pass")
            self.assertEqual(row["agent_steps"], 7)
            self.assertEqual(row["provider_calls"], 7)
            self.assertEqual(row["tool_calls"], 6)
            self.assertEqual(row["agent_test_runs"], 2)
            self.assertEqual(len(row["changed_files"]), 1)
            self.assertIsNone(row["cost_usd"])

    def test_step_limit_is_a_reported_failure(self):
        report = evaluate(ScriptedBenchmarkProvider, mode="offline-scripted",
                          cases=BENCHMARKS[:1], max_steps=1)
        row = report["runs"][0]
        self.assertFalse(row["success"])
        self.assertEqual(row["reason"], "step_limit")
        self.assertFalse(row["final_tests_passed"])
        self.assertEqual(report["summary"]["success_rate"], 0)

    def test_context_limit_is_a_reported_failure(self):
        report = evaluate(ScriptedBenchmarkProvider, mode="offline-scripted",
                          cases=BENCHMARKS[:1], context_chars=1)
        row = report["runs"][0]
        self.assertEqual(row["reason"], "context_limit")
        self.assertEqual(row["provider_calls"], 0)

    def test_provider_error_does_not_stop_other_cases_or_leak_body(self):
        class Broken:
            def complete(self, messages, tools):
                raise ProviderError("secret-provider-body")
        def factory(case):
            return Broken() if case == BENCHMARKS[0] else ScriptedBenchmarkProvider(case)
        report = evaluate(factory, mode="live", model="test-model", cases=BENCHMARKS[:2])
        self.assertEqual(report["summary"]["passed"], 1)
        self.assertEqual(report["runs"][0]["reason"], "execution_error")
        self.assertEqual(report["runs"][0]["error_type"], "ProviderError")
        self.assertNotIn("secret-provider-body", json.dumps(report))

    def test_passing_baseline_is_invalid_and_provider_is_not_called(self):
        case = Benchmark("already_fixed", "nothing", "module.py", "x = 1\n",
                         "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n",
                         "1", "2")
        def factory(case):
            self.fail("Provider must not run on passing baseline")
        report = evaluate(factory, mode="offline-scripted", cases=(case,))
        self.assertEqual(report["runs"][0]["reason"], "invalid_baseline")
        self.assertEqual(report["summary"]["passed"], 0)

    def test_test_file_changes_are_rejected(self):
        original = Tools.apply_patch
        def tamper(tools, **args):
            result = original(tools, **args)
            (tools.safety.root / "tests/test_case.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n def test_fake(self): pass\n")
            return result
        with patch.object(Tools, "apply_patch", tamper):
            report = evaluate(ScriptedBenchmarkProvider, mode="offline-scripted", cases=BENCHMARKS[:1])
        row = report["runs"][0]
        self.assertFalse(row["success"])
        self.assertEqual(row["reason"], "unexpected_file_changes")
        self.assertIn("tests/test_case.py", row["changed_files"])

    def test_independent_grade_rejects_false_success_from_agent_tests(self):
        original = Tools.run_tests
        def forged(tools):
            # First baseline run is real. Only the agent's subsequent test
            # calls in repo are forged; the fresh grading directory runs real tests.
            if tools.safety.root.name == "repo" and tools.revision:
                tools.verified_revision = tools.revision
                return {"passed": True, "exit_code": 0}
            return original(tools)
        class WrongPatch(ScriptedBenchmarkProvider):
            def complete(self, messages, tools):
                message = super().complete(messages, tools)
                for call in message.get("tool_calls", []):
                    if call["function"]["name"] == "apply_patch":
                        args = json.loads(call["function"]["arguments"])
                        args["new"] = "return 0"
                        call["function"]["arguments"] = json.dumps(args)
                return message
        with patch.object(Tools, "run_tests", forged):
            report = evaluate(WrongPatch, mode="offline-scripted", cases=BENCHMARKS[:1])
        self.assertEqual(report["runs"][0]["reason"], "final_tests_failed")
        self.assertFalse(report["runs"][0]["success"])

    def test_invalid_limits_are_rejected_before_running(self):
        for kwargs in ({"repeats": 0}, {"max_steps": 0}, {"context_chars": 0},
                       {"test_timeout": -1}, {"cases": ()}):
            with self.assertRaises(ValueError):
                evaluate(ScriptedBenchmarkProvider, mode="offline-scripted", **kwargs)

    def test_atomic_report_and_cli_case_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "reports/run.json"
            with redirect_stdout(StringIO()):
                code = main(["--case", "normalize_slug", "--output", str(destination)])
            self.assertEqual(code, 0)
            report = json.loads(destination.read_text())
            self.assertEqual(report["summary"]["runs"], 1)
            self.assertEqual(report["runs"][0]["case"], "normalize_slug")
            before = destination.read_bytes()
            with self.assertRaises(TypeError):
                write_report({"bad": object()}, destination)
            self.assertEqual(destination.read_bytes(), before)
            self.assertEqual(list(destination.parent.glob(".eval-*")), [])

    def test_live_requires_configuration_and_offline_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "report.json"
            with patch.dict(os.environ, {}, clear=True), patch("vancecode.cli.load_env"), redirect_stdout(StringIO()):
                self.assertEqual(main(["--live", "--output", str(destination)]), 2)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
