# V5 resource-priority release amendment

The final application policy now permits a V5 point whose energy loss is
slightly larger than a conservative comparator when it remains inside both the
frozen `1e-4` Ha cumulative-energy guard and strict chemical accuracy, and
provides a useful circuit-resource reduction.

This changes only the release choice. It does not rewrite the preregistered
strict-success labels or any raw result.

| Case | Selected point | Energy increase (Ha) | CNOT | Parameters | Total depth | CNOT depth | Blocks |
|---|---|---:|---:|---:|---:|---:|---:|
| LiH 3.0 Å | V4.1-equivalent | 8.69014e-5 | 58 | 8 | 92 | 30 | 8 |
| H6 1.5 Å | V5.1 resource point | 8.82143e-5 | 840 | 129 | 1520 | 300 | 76 |
| H6 3.0 Å | V5 raw resource winner | 7.84926e-5 | 741 | 138 | 1394 | 284 | 92 |
| BeH2 3.0 Å | V5 raw resource winner | 9.85183e-5 | 221 | 31 | 367 | 85 | 25 |

BeH2 is closest to the guard and therefore must always be reported with its
actual energy increase. It is acceptable under this application policy but
remains a failure under the original same-or-lower-energy strict comparison.
