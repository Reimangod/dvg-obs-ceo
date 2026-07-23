"""Independent audit for the LiH width-four breadth sensitivity."""

from __future__ import annotations

import json

from .baseline import ROOT
from .v5_s8_lih_energy_aware_audit import _digest, run_audit


RESULT = ROOT / "artifacts/v5/s8/lih-energy-aware-width4-v1/summary.json"
OUTPUT = ROOT / "artifacts/v5/s8/lih-energy-aware-width4-v1-audit.json"
CODE_TAG = "dvg-obs-v5-s8-lih-energy-aware-width4-code-v1"


def audit_width4(*, recompute_quantum: bool = True):
    audit = run_audit(
        recompute_quantum=recompute_quantum,
        result_path=RESULT,
        code_tag=CODE_TAG,
        expected_attempts=12,
        expected_rounds=2,
        expected_active_width=4,
        expected_terminal_catalogs=1,
        terminal_catalog_expected_work=None,
        scientific_status=(
            "valid-width4-no-endpoint-improvement-structural-floor-supported"
        ),
    )
    audit["interpretation"] = (
        "Width four exact-evaluated source ranks one through four and eight "
        "second-round candidates. It retained four paths but did not improve "
        "the 58-CNOT, 8-parameter endpoint. The preregistered stop rule blocks "
        "width eight because extra breadth did not justify its work."
    )
    audit.pop("audit_digest")
    audit["audit_digest"] = _digest(audit)
    return audit


if __name__ == "__main__":
    audit = audit_width4()
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    OUTPUT.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"passed": audit["passed"], "checks": len(audit["checks"])},
            sort_keys=True,
        )
    )
