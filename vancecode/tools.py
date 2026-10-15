"""Four core tools; edits use exact replacement, never shell patch commands."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from .safety import Safety, SafetyError

MAX_BYTES = 100_000


def schema(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}}


STRING = {"type": "string"}
SCHEMAS = [
    schema("read_file", "Read a UTF-8 file. Optional 1-based inclusive line range limits context.",
           {"path": STRING, "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1}}, ["path"]),
    schema("search_code", "Find literal text in repository files; empty query lists files.",
           {"query": STRING}, ["query"]),
    schema("apply_patch", "Replace exactly one occurrence of old with new in an existing file. Read first.",
           {"path": STRING, "old": STRING, "new": STRING}, ["path", "old", "new"]),
    schema("run_tests", "Run the configured unittest suite. No command arguments accepted.", {}, []),
]


class Tools:
    def __init__(self, safety: Safety, timeout: float = 30):
        if timeout <= 0:
            raise ValueError("Test timeout must be positive")
        self.safety, self.timeout = safety, timeout
        self.revision = 0
        self.verified_revision = None

    def execute(self, name: str, args: dict) -> dict:
        spec = next((s["function"]["parameters"] for s in SCHEMAS if s["function"]["name"] == name), None)
        try:
            if spec is None:
                raise ValueError("Unknown tool")
            if (not isinstance(args, dict) or not set(spec["required"]).issubset(args)
                    or not set(args).issubset(spec["properties"])):
                raise ValueError("Invalid tool arguments")
            for key, value in args.items():
                kind = spec["properties"][key]["type"]
                if kind == "string" and not isinstance(value, str):
                    raise ValueError(f"{key} must be a string")
                if kind == "integer" and (type(value) is not int or value < 1):
                    raise ValueError(f"{key} must be a positive integer")
            return {"ok": True, **getattr(self, name)(**args)}
        except (OSError, ValueError, UnicodeError) as exc:
            return {"ok": False, "error": str(exc)}

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None):
        target = self.safety.path(path)
        if target.stat().st_size > MAX_BYTES:
            raise ValueError("File too large; narrow the task")
        content = target.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        if end_line is not None and end_line < start_line:
            raise ValueError("end_line must be >= start_line")
        if start_line > max(1, len(lines)):
            raise ValueError(f"start_line exceeds file length ({len(lines)} lines)")
        end = min(end_line if end_line is not None else len(lines), len(lines))
        return {"path": path, "content": "".join(lines[start_line - 1:end]),
                "start_line": start_line, "end_line": end, "total_lines": len(lines),
                "partial": start_line > 1 or end < len(lines)}

    def search_code(self, query: str):
        matches = []
        visited = 0
        for directory, dirs, files in os.walk(self.safety.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in self.safety.blocked and not Path(directory, d).is_symlink())
            for name in sorted(files):
                visited += 1
                if visited > 5000:
                    return {"matches": matches, "truncated": True}
                relative = str(Path(directory, name).relative_to(self.safety.root))
                try:
                    content = self.read_file(relative)["content"]
                except (OSError, ValueError, UnicodeError):
                    continue
                for line, text in enumerate(content.splitlines(), 1):
                    if not query or query in text:
                        matches.append({"path": relative, "line": line, "text": text[:300]})
                        if not query:
                            break
                        if len(matches) >= 100:
                            return {"matches": matches, "truncated": True}
                if len(matches) >= 100:
                    return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    def apply_patch(self, path: str, old: str, new: str):
        target = self.safety.path(path, write=True)
        content = self.read_file(path)["content"]
        if not old or content.count(old) != 1:
            raise ValueError("old must match exactly once; reread the file")
        updated = content.replace(old, new, 1)
        if len(updated.encode()) > MAX_BYTES:
            raise ValueError("Updated file too large")
        self.safety.require(f"Edit {path}:\n- {old}\n+ {new}")
        target.write_text(updated, encoding="utf-8")
        self.revision += 1
        return {"path": path, "revision": self.revision}

    def run_tests(self):
        self.safety.require("Run repository Python tests (executes repository code)")
        # Do not forward API keys or the caller's environment into repo tests.
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR", "LANG") if key in os.environ}
        # -B only prevents writes; it does not prevent reading existing .pyc.
        # A fresh pycache prefix avoids stale same-size/same-second source caches.
        with tempfile.TemporaryDirectory(prefix="vancecode-pycache-") as cache_dir, tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                [sys.executable, "-I", "-B", "-X", f"pycache_prefix={cache_dir}", "-c",
                 "import sys,unittest; sys.path.insert(0,'.'); "
                 "suite=unittest.defaultTestLoader.discover('tests'); "
                 "count=suite.countTestCases(); print('Collected',count,'tests',flush=True); "
                 "result=unittest.TextTestRunner(verbosity=2).run(suite); "
                 "sys.exit(0 if count and result.wasSuccessful() else 1)"],
                cwd=self.safety.root, env=env, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True)
            timed_out = False
            try:
                process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # Kill descendants even when the parent exited normally.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            output.seek(0)
            data = output.read(MAX_BYTES + 1)
        passed = process.returncode == 0 and not timed_out
        self.verified_revision = self.revision if passed else None
        return {"passed": passed, "exit_code": process.returncode, "timed_out": timed_out,
                "output": data[:MAX_BYTES].decode(errors="replace"), "truncated": len(data) > MAX_BYTES}
