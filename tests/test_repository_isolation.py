from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_dependency_is_absent() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_isolation.py")],
        cwd=ROOT,
        check=True,
    )


def test_upstream_commit_is_pinned() -> None:
    value = subprocess.check_output(
        ["git", "-C", str(ROOT / "vendor" / "ceo-adapt-vqe"), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    assert value == "a3f89d03e6a03c89767d3cf8ee7657a57653dda0"


def test_upstream_worktree_is_clean() -> None:
    value = subprocess.check_output(
        ["git", "-C", str(ROOT / "vendor" / "ceo-adapt-vqe"), "status", "--porcelain"],
        text=True,
    )
    assert value == ""

