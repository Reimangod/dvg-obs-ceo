# V4-S6 calibration and pre-LiH freeze

V4-S6 freezes all deterministic search, resource-recount, exact-attempt, and
optimizer bounds before executing V4 on the stored LiH checkpoint. The bounds
are derived only from the preregistered H2/H4 evidence.

The H2/H4 first-accuracy set contains 17 single-candidate outcomes and no
candidate whose predicted or actual loss is at most `1e-4` Hartree. Therefore
positive-class precision, recall, and probability of safety are unavailable.
The joint confidence thresholds merely reject diagnostics outside outward-
rounded H2/H4 ranges. Held-out joint secants are unavailable and are not
relabeled as internal evidence.

This limitation does not weaken the final accuracy guard: a LiH transaction can
commit only after independent exact energy, state, constraint, stationarity,
optimizer, and full-resource checks. It does mean the surrogate may miss useful
candidates and that no calibrated screening-success claim is permitted.

No threshold, candidate family, ranking order, or budget may change after the
V4 LiH result under this configuration version.
