# S7: Transaction, independent acceptance, and rollback

## Outcome

S7 implements a fail-closed compression transaction. A candidate can replace the
current ansatz only after every registered energy, accuracy, state, constraint,
KKT, transformation, optimizer-path, and full-circuit resource check passes.
Failure restores the ansatz, coefficients, energy, gradient, recycled inverse
Hessian, statevector, work counters, metadata, ADAPT iteration, and Python/NumPy
RNG states.

## Commit protocol

1. Validate the source runtime.
2. Capture an exact float64/complex128 snapshot and RNG states.
3. Write and `fsync` `attempt.json` and `snapshot.json` in an exclusive staging
   directory.
4. Stage all candidate evidence without overwriting an existing record.
5. Bind an accepted decision to before/after energy, parameter count, and full
   circuit structure digests.
6. Write and `fsync` `commit.json`, then atomically rename staging to committed.
7. On any exception, rejection, timeout, NaN, or scope exit without commit,
   restore the exact snapshot and atomically retain the attempt under `failed/`.

An orphan staging directory after abrupt process loss is always rolled back from
its durable snapshot. It is never inferred to be committed.

## Independent acceptance gates

The following gates are evaluated separately and retained in the decision:

- finite values and physical scalar domains;
- actual local energy increase and absolute chemical accuracy;
- independent energy agreement and state fidelity;
- native constraint residual and KKT residual;
- transformation semantic validation and full resource recount;
- Pareto non-worsening for CNOT count, CNOT depth, total depth, parameters, and
  logical blocks, with at least one strict improvement;
- successful primary optimizer, or one completed preregistered fallback followed
  by the same independent gates.

`optimizer.success` is neither ignored nor sufficient by itself.

## Failure evidence

The registered probe terminated a child process with `os._exit(17)`, bypassing
context managers and in-memory cleanup. A fresh runtime was restored from the
durable snapshot with the identical snapshot digest. Exception, NaN, partial
artifact write, deadline, rejected acceptance, nested transaction, and cross-
runtime concurrent transaction paths were also tested. The full suite passed 68
tests; the 95 warnings originate from the pinned paper-era dependency stack and
are retained rather than hidden in normal runs.

## Concurrency boundary

Legacy Python and NumPy RNG states are process-global. Therefore compression
transactions are deliberately serialized within one process. Parallel molecular
runs must use separate processes and separate artifact roots until runtime-owned
random generators are introduced. This restriction prevents one rollback from
silently changing another run's random stream.

## Claim boundary

S7 proves recovery and acceptance-control behavior. Its synthetic energies and
resource values are fixtures, not molecular performance evidence. Predictor
quality, safe-pruning rates, and useful circuit reduction remain S8-S11 claims.
