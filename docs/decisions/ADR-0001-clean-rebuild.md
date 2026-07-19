# ADR-0001: Clean rebuild on the paper-era DVG_CEO baseline

Status: accepted  
Date: 2026-07-20

## Decision

Build DVG-OBS-CEO in a new repository. Pin the unmodified official upstream at
the numerically reproduced paper-era commit. Do not reuse the legacy V2 source,
schemas, manifests, or artifacts.

## Rationale

The legacy extension targeted an MVP_CEO terminal ansatz and mixed null-space
coordinates with native target coordinates. Its calibration also compared
quantities with different energy references. Reusing it would make provenance
and causal interpretation ambiguous.

## Consequences

Useful engineering concepts must be reimplemented and independently tested.
This costs additional development time but creates a clean scientific audit
trail and prevents legacy assumptions from silently entering the new method.

