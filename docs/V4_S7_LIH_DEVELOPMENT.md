# V4-S7 stored-checkpoint LiH development experiment

V4-S7 reconstructs the immutable LiH 3 Å first-accuracy checkpoint. It does not
run a new CEO* or ordinary ADAPT ansatz-growth iteration. The source energy,
statevector digest, full circuit resources, and checkpoint digest must all
independently match before screening begins.

Global OBS search uses only the recycled inverse Hessian, checkpoint gradient,
registered transformations, frozen confidence range, and paper-era structural
resource counts. Actual candidate energy and FCI energy are not selector inputs.

Up to two candidates per co-primary endpoint and four unique structures are
optimized. Every attempt starts from a fresh source clone in its own atomic
transaction. Commit requires the unchanged cumulative `1e-4` Hartree energy
budget, independent energy/state recomputation, two-path target/source gradient
certificate, constraint and KKT residuals, and the four preregistered
componentwise resource guards. A rejected attempt is fully rolled back and
cannot alter later attempts.

LiH was observed while developing earlier versions, so this is development
evidence only. It cannot support an out-of-sample or general-superiority claim.

Execution protocol v1.1 includes the source-slot ordering correction documented
in `docs/incidents/V4_S7_V1_LEXICOGRAPHIC_SLOT_ORDER.md`; thresholds, candidate
families, budgets, checkpoint, and ranking are unchanged from v1.
