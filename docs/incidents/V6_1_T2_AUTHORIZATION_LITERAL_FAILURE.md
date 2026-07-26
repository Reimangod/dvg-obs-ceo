# V6.1 T2 authorization literal failure

The first T2 execution completed the statevector work but stopped before
artifact creation because a Python dictionary used the JSON literal `false`
instead of Python `False`. Atomic write-new behavior ensured that no partial
or ambiguous result artifact existed.

The correction moved stage authorization into a tested helper. T2 is allowed
to authorize T3/T4 only after a Go decision and can never authorize T5/T6
performance execution directly. No numerical result was inspected or retained
from the failed process, and the preregistered metric and thresholds are
unchanged.

The corrected rerun exposed a second write-boundary defect: a NumPy boolean
from the separation-ratio comparison was not standard JSON serializable.
Again, canonical hashing failed before atomic artifact creation. The ratio and
all gate results are now converted explicitly to Python scalar types, and the
authorization payload is exercised through the canonical JSON encoder in the
regression test. No partial result was produced by either failed execution.
