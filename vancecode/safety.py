"""Policy checks are guardrails, not an OS sandbox."""
from pathlib import Path


class SafetyError(ValueError):
    pass


class Safety:
    blocked = {".git", ".venv", "venv", "node_modules", "__pycache__", ".ssh", ".aws"}

    def __init__(self, root: Path, approve):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Repository must be a directory")
        self.approve = approve

    def path(self, name: str, write: bool = False) -> Path:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise SafetyError("Use a repository-relative path without '..'")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise SafetyError("Path escapes repository")
        parts = set(relative.parts) | set(path.relative_to(self.root).parts)
        if parts & self.blocked or any(p.startswith(".env") or p.endswith((".pem", ".key")) for p in parts):
            raise SafetyError("Protected file or directory")
        if write and ("tests" in parts or path.name.startswith("test_") or path.name.endswith("_test.py")):
            raise SafetyError("Test files are read-only in Milestone 1")
        return path

    def require(self, action: str):
        if not self.approve(action):
            raise SafetyError("User denied operation")
