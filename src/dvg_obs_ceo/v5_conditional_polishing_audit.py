"""Independent invariant audit for V5-S6 conditional polishing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from .polishing import TrustNCGConfig
from .quadratic import ConstraintTargetIR
from .v3_protocol import _write_exclusive
from .v5_conditional_polishing import (
    SECOND_START_TRIGGER,
    ConditionalPolishingConfig,
    PolishingEligibility,
    polish_target_native_conditionally,
)


def run_audit() -> dict[str, Any]:
    transformation = ConstraintTargetIR.create(
        constraint_matrix=[[1.0, 1.0]],
        constraint_rhs=[0.0],
        offset=[0.0, 0.0],
        jacobian=[[1.0], [-1.0]],
        source_slots=("a", "b"),
        target_slots=("z",),
        generator_normalization="audit",
        orientation="audit",
    )

    def energy(source):
        return float((source[0] - 0.2) ** 2 + (source[1] + 0.2) ** 2 - 1.0)

    def gradient(source):
        return np.asarray([2.0 * (source[0] - 0.2), 2.0 * (source[1] + 0.2)])

    primary = polish_target_native_conditionally(
        transformation,
        [0.8, -0.8],
        [0.2, -0.2],
        energy,
        gradient,
        PolishingEligibility(True, True, True, True),
    )
    second = polish_target_native_conditionally(
        transformation,
        [1.0, -1.0],
        [0.2, -0.2],
        energy,
        gradient,
        PolishingEligibility(True, True, True, True),
        config=ConditionalPolishingConfig(
            polisher=TrustNCGConfig(maximum_gradient_vector_evaluations=1),
            enable_second_least_squares_start=True,
            second_start_trigger=SECOND_START_TRIGGER,
            maximum_total_energy_evaluations=4,
            maximum_total_gradient_vector_evaluations=2,
            maximum_total_hessian_vector_products=4,
        ),
    )
    callback_calls = 0

    def forbidden(_):
        nonlocal callback_calls
        callback_calls += 1
        raise AssertionError("ineligible callback was called")

    blocked = polish_target_native_conditionally(
        transformation,
        [0.2, -0.2],
        [0.2, -0.2],
        forbidden,
        forbidden,
        PolishingEligibility(True, False, True, True),
    )
    checks = {
        "primary_polishing_succeeds": primary["success"],
        "target_map_preserves_constraint": primary["constraint_residual_infinity"] <= 1e-10,
        "frozen_gradient_infinity_gate_holds": primary["gradient_infinity"] <= 1e-8,
        "registered_second_start_can_recover": second["success"] and second["selected_start"] == "registered-least-squares-reference",
        "second_start_work_is_counted": second["work"]["gradient_vector_evaluations"] == 2,
        "resource_failure_cannot_be_polished": not blocked["performed"] and callback_calls == 0,
        "measurement_cost_not_relabelled": primary["paper_measurement_cost"] is None,
        "rms_is_diagnostic_only": "gradient_rms" in primary and primary["gradient_infinity"] <= 1e-8,
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s6-conditional-polishing-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "primary": primary,
        "registered_second_start": second,
        "blocked_probe": blocked,
        "claim_boundary": "Synthetic target-coordinate audit only; no molecular VQE performance claim.",
    }
    if not result["passed"]:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"V5-S6 audit failed: {failed}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run_audit()
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()
