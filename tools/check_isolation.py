"""Fail if the clean repository references the legacy V2 implementation."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCANNED_ROOTS = (ROOT / "src", ROOT / "tests")
FORBIDDEN_IMPORT = "adaptvqe_prune_reuse"


def main() -> int:
    violations: list[str] = []
    for scanned_root in SCANNED_ROOTS:
        for path in scanned_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if FORBIDDEN_IMPORT in text:
                violations.append(
                    f"{path.relative_to(ROOT)}: forbidden legacy package reference"
                )
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if FORBIDDEN_IMPORT in pyproject:
        violations.append("pyproject.toml: forbidden legacy dependency")
    if violations:
        raise SystemExit("legacy isolation failed:\n" + "\n".join(violations))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
