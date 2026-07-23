"""Independent audit for the LiH energy-aware third-round extension."""

from __future__ import annotations

import json

from .baseline import ROOT
from .v5_s8_lih_energy_aware_audit import _digest, run_audit


RESULT = ROOT / "artifacts/v5/s8/lih-energy-aware-width2-round3-v1/summary.json"
OUTPUT = ROOT / "artifacts/v5/s8/lih-energy-aware-width2-round3-v1-audit.json"
CODE_TAG = "dvg-obs-v5-s8-lih-energy-aware-round3-code-v1"


def audit_round3(*, recompute_quantum: bool = True):
    audit = run_audit(
        recompute_quantum=recompute_quantum,
        result_path=RESULT,
        code_tag=CODE_TAG,
        expected_attempts=6,
        expected_rounds=3,
        expected_terminal_catalogs=2,
        scientific_status=(
            "valid-round3-no-endpoint-improvement-structural-floor-indicated"
        ),
    )
    audit["interpretation"] = (
        "The low-energy branch continued to 94 CNOT and 12 parameters, while "
        "the stronger branch again converged to the catalog-terminal 58-CNOT, "
        "8-parameter structure. More rounds are not justified without expanding "
        "the transformation family."
    )
    audit.pop("audit_digest")
    audit["audit_digest"] = _digest(audit)
    return audit


if __name__ == "__main__":
    audit = audit_round3()
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
