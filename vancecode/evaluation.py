"""Repeatable harness evaluation with fresh repos and independent final grading."""
import argparse
from datetime import datetime, timezone
from difflib import unified_diff
import json
import os
from pathlib import Path
import tempfile
import time

from .agent import Agent
from .benchmarks import BENCHMARKS, Benchmark
from .context import ContextManager
from .provider import OpenAICompatibleProvider, ProviderError
from .safety import Safety
from .tools import Tools
from .traffic import PacedProvider, RequestSchedule


class ScriptedBenchmarkProvider:
    """Known reference patch: validates mechanics, never measures LLM ability."""
    def __init__(self, case: Benchmark):
        self.case, self.index = case, 0

    def complete(self, messages, tools):
        case = self.case
        sequence = [("search_code", {"query": ""}),
                    ("read_file", {"path": case.filename}),
                    ("read_file", {"path": "tests/test_case.py"}),
                    ("run_tests", {}),
                    ("apply_patch", {"path": case.filename, "old": case.old, "new": case.new}),
                    ("run_tests", {})]
        if self.index == len(sequence):
            return {"role": "assistant", "content": "Reference patch applied and tests passed."}
        name, args = sequence[self.index]
        self.index += 1
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": f"eval_{self.index}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}]}


def materialize(case: Benchmark, root: Path, *, holdout: bool = False):
    root.mkdir()
    (root / "tests").mkdir()
    (root / case.filename).write_text(case.source, encoding="utf-8")
    (root / "tests/test_case.py").write_text(case.holdout_tests if holdout else case.tests, encoding="utf-8")
    (root / "README.md").write_text(case.task, encoding="utf-8")


def snapshot(root: Path) -> dict:
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in dirs + names:
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            if path.is_symlink():
                files[relative] = ("symlink", os.readlink(path))
            elif path.is_file():
                files[relative] = ("file", path.read_bytes())
    return files


def evaluate(provider_factory, *, mode: str, cases=BENCHMARKS, repeats: int = 1,
             max_steps: int = 20, context_chars: int = 200_000,
             test_timeout: float = 30, model: str | None = None,
             request_interval: float = 0, rate_limit_retries: int = 0, on_wait=None) -> dict:
    if mode not in ("offline-scripted", "live"):
        raise ValueError("Unknown evaluation mode")
    if repeats < 1 or max_steps < 1 or test_timeout <= 0 or not cases:
        raise ValueError("Evaluation requires cases and positive limits")
    ContextManager(context_chars)  # Validate once before executing anything.
    schedule = RequestSchedule(request_interval, rate_limit_retries, on_wait=on_wait)
    rows = []
    for case in cases:
        for attempt in range(1, repeats + 1):
            started = time.monotonic()
            transport_before = (schedule.requests, schedule.retry_count, schedule.wait_seconds)
            row = {"case": case.name, "attempt": attempt, "success": False,
                   "reason": "not_started", "agent_steps": 0, "provider_calls": 0,
                   "tool_calls": 0, "tool_errors": 0, "agent_test_runs": 0,
                   "context_compactions": 0, "max_request_chars": 0,
                   "baseline_failed": False, "final_tests_passed": False,
                   "visible_tests_passed": None, "holdout_configured": bool(case.holdout_tests),
                   "holdout_tests_passed": None,
                   "candidate_patch": None,
                   "changed_files": [], "input_tokens": None, "output_tokens": None,
                   "cost_usd": None}

            def emit(event):
                if event.get("type") == "context":
                    row["provider_calls"] += 1
                    row["max_request_chars"] = max(row["max_request_chars"], event["request_chars"])
                    row["context_compactions"] += int(event["dropped_groups"] > 0)
                else:
                    row["tool_calls"] += 1
                    row["tool_errors"] += int(not event["result"]["ok"])
                    row["agent_test_runs"] += int(event["tool"] == "run_tests")

            try:
                with tempfile.TemporaryDirectory(prefix="vancecode-eval-") as directory:
                    root = Path(directory) / "repo"
                    materialize(case, root)
                    before = snapshot(root)
                    tools = Tools(Safety(root, lambda _: True), test_timeout)
                    baseline = tools.execute("run_tests", {})
                    row["baseline_failed"] = baseline.get("ok", False) and not baseline.get("passed", True) and not baseline.get("timed_out", True)
                    if not row["baseline_failed"]:
                        row["reason"] = "invalid_baseline"
                    else:
                        result = Agent(PacedProvider(provider_factory(case), schedule), tools, max_steps=max_steps,
                                       emit=emit, context=ContextManager(context_chars)).run(case.task)
                        row["agent_steps"] = result.steps
                        after = snapshot(root)
                        row["changed_files"] = sorted(name for name in before.keys() | after.keys()
                                                      if before.get(name) != after.get(name))
                        # Only the implementation file may change. A final test
                        # run is made from pristine fixture tests in a fresh repo.
                        integrity = set(row["changed_files"]).issubset({case.filename})
                        candidate = after.get(case.filename)
                        if candidate is not None and candidate[0] == "file":
                            row["candidate_patch"] = "".join(unified_diff(
                                case.source.splitlines(keepends=True),
                                candidate[1].decode("utf-8", errors="replace").splitlines(keepends=True),
                                fromfile="a/" + case.filename, tofile="b/" + case.filename))
                        if not integrity or candidate is None or candidate[0] != "file":
                            row["reason"] = "unexpected_file_changes"
                        else:
                            grade_root = Path(directory) / "grade"
                            materialize(case, grade_root)
                            (grade_root / case.filename).write_bytes(candidate[1])
                            grade = Tools(Safety(grade_root, lambda _: True), test_timeout).execute("run_tests", {})
                            row["visible_tests_passed"] = grade.get("ok", False) and grade.get("passed", False)
                            if row["visible_tests_passed"] and case.holdout_tests:
                                holdout_root = Path(directory) / "holdout"
                                materialize(case, holdout_root, holdout=True)
                                (holdout_root / case.filename).write_bytes(candidate[1])
                                holdout = Tools(Safety(holdout_root, lambda _: True), test_timeout).execute("run_tests", {})
                                row["holdout_tests_passed"] = holdout.get("ok", False) and holdout.get("passed", False)
                            row["final_tests_passed"] = row["visible_tests_passed"] and (
                                not case.holdout_tests or row["holdout_tests_passed"] is True)
                            row["success"] = result.success and row["final_tests_passed"]
                            row["reason"] = ("verified_pass" if row["success"] else
                                             result.reason if not result.success else
                                             "final_tests_failed" if not row["visible_tests_passed"] else
                                             "holdout_tests_failed")
            except Exception as exc:
                # Do not persist provider bodies, credentials or arbitrary repo text.
                row["reason"] = "execution_error"
                row["error_type"] = type(exc).__name__
                if isinstance(exc, ProviderError):
                    row["provider_error"] = exc.diagnostic()
                row["agent_steps"] = None
            row["elapsed_seconds"] = round(time.monotonic() - started, 4)
            row["transport_requests"] = schedule.requests - transport_before[0]
            row["rate_limit_retries"] = schedule.retry_count - transport_before[1]
            row["request_wait_seconds"] = round(schedule.wait_seconds - transport_before[2], 4)
            rows.append(row)
    passed = sum(row["success"] for row in rows)
    completed_steps = [row["agent_steps"] for row in rows if row["agent_steps"] is not None]
    return {"schema_version": 2, "benchmark_version": "2", "mode": mode, "model": model if mode == "live" else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "limitations": ["Scripted runs measure harness mechanics, not model capability.",
                             "Visible and held-out fixture tests are limited regression checks, not proof of correctness.",
                             "Held-out tests are withheld from tool-visible repos, not secured against hostile local code.",
                             "Token usage and cost are unavailable and reported as null.",
                             "Repository tests execute locally without an OS sandbox."],
            "config": {"repeats": repeats, "max_steps": max_steps, "context_chars": context_chars,
                       "test_timeout": test_timeout, "request_interval": request_interval,
                       "rate_limit_retries": rate_limit_retries},
            "summary": {"runs": len(rows), "passed": passed, "failed": len(rows) - passed,
                        "success_rate": passed / len(rows),
                        "visible_passed": sum(r["visible_tests_passed"] is True for r in rows),
                        "holdout_passed": sum(r["holdout_tests_passed"] is True for r in rows),
                        "holdout_failed": sum(r["holdout_tests_passed"] is False for r in rows),
                        "holdout_skipped": sum(r["holdout_tests_passed"] is None for r in rows),
                        "mean_agent_steps": sum(completed_steps) / len(completed_steps) if completed_steps else None,
                        "runs_with_step_count": len(completed_steps),
                        "elapsed_seconds": round(sum(row["elapsed_seconds"] for row in rows), 4)},
            "runs": rows}


def write_report(report: dict, destination: Path):
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".eval-", suffix=".json", delete=False) as file:
            temporary = Path(file.name)
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary.replace(destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate VanceCode on trusted built-in fixtures")
    parser.add_argument("--live", action="store_true", help="Call configured LLM API (billed by your provider)")
    parser.add_argument("--case", action="append", choices=[c.name for c in BENCHMARKS])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--context-chars", type=int, default=200_000)
    parser.add_argument("--test-timeout", type=float, default=30)
    parser.add_argument("--request-interval", type=float, default=0, help="Minimum seconds between model requests (0..60)")
    parser.add_argument("--rate-limit-retries", type=int, default=0, help="Extra attempts per model turn after HTTP 429 (0..5)")
    parser.add_argument("--output", type=Path, default=Path("evaluation-report.json"))
    args = parser.parse_args(argv)
    try:
        model = None
        if args.live:
            from .cli import load_env
            load_env(Path.cwd() / ".env")
            model = os.getenv("VANCECODE_MODEL", "")
            def factory(case):
                return OpenAICompatibleProvider(os.getenv("OPENAI_API_KEY", ""), model,
                                                os.getenv("VANCECODE_BASE_URL", "https://api.openai.com/v1"))
            factory(None)  # Fail missing configuration before executing cases.
        else:
            factory = ScriptedBenchmarkProvider
        cases = tuple(c for c in BENCHMARKS if not args.case or c.name in args.case)
        report = evaluate(factory, mode="live" if args.live else "offline-scripted", cases=cases,
                          repeats=args.repeats, max_steps=args.max_steps,
                          context_chars=args.context_chars, test_timeout=args.test_timeout, model=model,
                          request_interval=args.request_interval, rate_limit_retries=args.rate_limit_retries,
                          on_wait=lambda seconds: print(f"Waiting {seconds:.1f}s before next model request...", flush=True))
        write_report(report, args.output)
        summary = report["summary"]
        print(f"{report['mode']}: {summary['passed']}/{summary['runs']} verified passes; report: {args.output}")
        for row in report["runs"]:
            diagnostic = row.get("provider_error")
            if diagnostic:
                print(f"  {row['case']}: {diagnostic['kind']}" +
                      (f" (HTTP {diagnostic['http_status']})" if diagnostic["http_status"] else "") +
                      "".join(f" / {diagnostic[key]}" for key in (
                          "provider_status", "provider_reason", "request_issue") if key in diagnostic))
                if diagnostic.get("provider_message"):
                    print("    " + diagnostic["provider_message"])
        return 0 if not summary["failed"] else 1
    except (ValueError, OSError) as exc:
        print(f"Evaluation error: {exc}")
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
