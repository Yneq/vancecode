import argparse
import json
import os
from pathlib import Path
import sys
from .agent import Agent
from .provider import OpenAICompatibleProvider, ProviderError
from .safety import Safety
from .tools import Tools
from .context import ContextManager


def load_env(path: Path):
    """Minimal KEY=value loader; existing environment wins; no shell expansion."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip().replace("_", "a").isalnum():
            raise ValueError("Invalid .env line; use KEY=value")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="VanceCode: a minimal coding agent")
    parser.add_argument("task")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--model")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--test-timeout", type=float, default=30)
    parser.add_argument("--context-chars", type=int, default=200_000, help="JSON context budget including tool schemas")
    parser.add_argument("--tool-result-chars", type=int, default=12_000, help="Large tool result preview threshold")
    parser.add_argument("--yes", action="store_true", help="Approve edits and execution in a trusted repo")
    args = parser.parse_args(argv)

    def approve(action):
        if args.yes:
            return True
        print(action, file=sys.stderr)
        try:
            return input("Allow? [y/N] ").strip().lower() == "y"
        except EOFError:
            return False

    def emit(event):
        if event.get("type") == "context":
            print(f"[{event['step']}] context: {event['request_chars']} chars, "
                  f"{event['dropped_groups']} older groups omitted, "
                  f"{event['trimmed_results']} results shortened", flush=True)
            return
        result = event["result"]
        print(f"[{event['step']}] {event['tool']}: " + json.dumps(result, ensure_ascii=False), flush=True)

    try:
        load_env(Path.cwd() / ".env")
        provider = OpenAICompatibleProvider(
            os.getenv("OPENAI_API_KEY", ""), args.model or os.getenv("VANCECODE_MODEL", ""),
            os.getenv("VANCECODE_BASE_URL", "https://api.openai.com/v1"))
        tools = Tools(Safety(args.repo, approve), args.test_timeout)
        context = ContextManager(args.context_chars, args.tool_result_chars)
        result = Agent(provider, tools, args.max_steps, emit, context=context).run(args.task)
        print(f"\n{result.reason}: {result.answer}")
        return 0 if result.success else 1
    except (ProviderError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
