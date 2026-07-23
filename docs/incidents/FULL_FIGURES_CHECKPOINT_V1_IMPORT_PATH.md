# Full-figures checkpoint v1 import-path incident

The first `h6-1.5` invocation stopped during preflight with
`ModuleNotFoundError: adaptvqe`. The runner verified the submodule commit but
did not call the existing upstream loader that registers the vendored package
path before importing the H6 and BeH2 molecule factories.

No molecule construction, energy evaluation, ADAPT iteration, progress ledger,
or result artifact occurred. Protocol v1.1 calls the existing pinned upstream
loader before the imports. Molecules, thresholds, seeds, stopping rule, V4
configuration, and claim boundaries are unchanged.
