"""Deterministic harness integration check; this is NOT an autonomous LLM."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vancecode.agent import Agent
from vancecode.safety import Safety
from vancecode.tools import Tools
from vancecode.context import ContextManager


class ScriptedProvider:
    """Deliberately wrong first patch exercises failure feedback and retry."""
    def __init__(self):
        self.index = 0
        self.trace = []

    def complete(self, messages, tools):
        original = "return (subtotal + shipping_cents) * (100 - discount_percent) // 100"
        wrong = "return subtotal * (100 - discount_percent) // 100"
        fixed = wrong + " + shipping_cents"
        sequence = [
            ("search_code", {"query": ""}),
            ("read_file", {"path": "pricing.py"}),
            ("read_file", {"path": "tests/test_pricing.py"}),
            ("run_tests", {}),
            ("apply_patch", {"path": "pricing.py", "old": original, "new": wrong}),
            ("run_tests", {}),
            ("apply_patch", {"path": "pricing.py", "old": wrong, "new": fixed}),
            ("run_tests", {}),
        ]
        if messages[-1]["role"] == "tool":
            self.trace.append(json.loads(messages[-1]["content"]))
        if self.index == len(sequence):
            return {"role": "assistant", "content": "Discount merchandise first, then add shipping. All 4 tests passed."}
        name, args = sequence[self.index]
        self.index += 1
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": f"call_{self.index}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}]}


def run_demo(emit=None, context=None):
    source = Path(__file__).resolve().parents[1] / "examples/buggy_repo"
    with tempfile.TemporaryDirectory(prefix="vancecode-demo-") as directory:
        repo = Path(directory) / "repo"
        shutil.copytree(source, repo, ignore=shutil.ignore_patterns("__pycache__"))
        provider = ScriptedProvider()
        result = Agent(provider, Tools(Safety(repo, lambda action: True)), emit=emit,
                       context=context).run("Fix pricing")
        outcomes = [r["passed"] for r in provider.trace if "passed" in r]
        assert outcomes == [False, False, True], outcomes
        assert result.success
        return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Offline scripted harness demo, no LLM calls")
    parser.add_argument("--context-chars", type=int, default=200_000)
    parser.add_argument("--tool-result-chars", type=int, default=12_000)
    args = parser.parse_args()
    result = run_demo(lambda e: print(json.dumps(e, ensure_ascii=False)),
                      ContextManager(args.context_chars, args.tool_result_chars))
    print(result.reason + ": " + result.answer)
