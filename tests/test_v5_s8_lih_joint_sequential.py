import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_joint_sequential_freeze_binds_parent_and_inherited_search_budget():
    manifest = json.loads(
        (ROOT / "manifests/v5-s8-lih-joint-sequential-v1.json").read_text()
    )
    parent = manifest["parent_single_catalog_evidence"]
    budget = manifest["search_budget_source"]
    assert hashlib.sha256((ROOT / parent["result_path"]).read_bytes()).hexdigest() == parent["result_sha256"]
    assert hashlib.sha256((ROOT / parent["audit_path"]).read_bytes()).hexdigest() == parent["audit_sha256"]
    assert hashlib.sha256((ROOT / budget["path"]).read_bytes()).hexdigest() == budget["sha256"]
    assert manifest["algorithm"]["catalog_rebuilt_after_commit"] is True
    assert manifest["algorithm"]["threshold_relaxation"] is False
