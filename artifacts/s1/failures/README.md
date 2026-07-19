# S1 failure retention

`lih-cli-argument-collision-invalid.json` came from an execution in which PySCF
interpreted the extension's process-wide `--artifact` argument as its own output
path. The scientific calculation reached the expected checkpoint, but the
wrapper terminated with an artifact overwrite refusal. It is retained for
audit only and is excluded from parity and all later comparisons.

The wrapper now clears extension arguments from `sys.argv` after parsing. The
formal S1 result is `../lih-3a-baseline-rerun.json`, produced by a complete new
execution after that fix.

