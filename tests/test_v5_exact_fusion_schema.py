import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "v5-exact-fusion-result-v1.schema.json"
ARTIFACTS = (
    ROOT / "artifacts" / "v5" / "s10" / "exact-fusion-gate-v1.json",
    ROOT / "artifacts" / "v5" / "s11" / "h6-1.5-exact-fusion-v1.json",
    ROOT / "artifacts" / "v5" / "s11" / "h6-1.5-s9-fusion-integration-v1.json",
)


def test_all_exact_fusion_result_artifacts_match_the_versioned_schema() -> None:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    for path in ARTIFACTS:
        validator.validate(json.loads(path.read_text(encoding="utf-8")))
