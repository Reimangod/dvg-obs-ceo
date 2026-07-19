# DVG-OBS-CEO 新規実装・公平比較計画

Version: 1.0-draft  
作成日: 2026-07-19  
対象: noiseless exact-statevector simulation  
仮称: **DVG-OBS-CEO**

## 0. 結論

本計画では、旧 `v2-implementation` を改修・流用しない。論文時期の公式
CEO-ADAPT-VQE*を正しいbaselineとして固定し、その外側に新しい実装を一から作る。

新方式の中心は、CEO-ADAPT-VQE*が最適化のために保持する近似逆Hessianを、
DVG_CEOが実際に生成したOVP/MVP混合blockの構造的圧縮へ再利用することである。

主張の順序は次に固定する。

1. 正しいbaselineを再現できる。
2. 数式とtarget parameter座標が一致する。
3. 削減後もaccuracyとKKT条件を満たす。
4. 同一accuracyで実回路資源が厳密に減る。
5. その削減を得るための追加classical/quantum workを全て報告する。
6. OBSがmagnitude/position-based pruningより有効かをablationで検証する。

## 1. 旧V2との完全分離

### 1.1 名称と配置

- 新方式名: `DVG-OBS-CEO`
- 新repository候補: `Reimangod/dvg-obs-ceo`（Private）
- 新local root候補: `.../dvg-obs-ceo`
- Python namespace候補: `dvg_obs_ceo`
- artifact prefix: `dvg-obs-ceo-v1`
- schema、protocol、result IDは旧V2と共有しない。

### 1.2 禁止事項

- `v2-implementation/research-extension`からコードをコピーしない。
- 旧V2 packageをimportしない。
- 旧V2のmanifest、threshold、schema、candidate IDを継承しない。
- 旧V2のLiH結果を新方式のdevelopment dataとして使わない。
- 旧V2 artifactを新方式の成功証拠として使わない。
- 旧V2を削除・上書きせず、`legacy-exploratory`としてread-only保存する。

旧V2から利用してよいのは、既に発見された失敗要因をrequirementsへ反映することだけである。
実装の正しさは新しいunit/property/integration testによって独立に証明する。

## 2. 正しいbaselineの固定

### 2.1 Canonical baseline

LiH 3 Åのcanonical CEO-ADAPT-VQE* baselineを次で固定する。

- upstream source commit: `a3f89d03e6a03c89767d3cf8ee7657a57653dda0`
- pool: `DVG_CEO`
- TETRIS: ON
- Hessian recycling: ON
- selection: gradient
- threshold: `1e-6`
- seed: `0`
- basis: STO-3G
- mapping: Jordan-Wigner
- shots: none
- noise: none
- primary checkpoint: first strict chemical-accuracy crossing

再現済みreference:

- first chemical-accuracy iteration: 5
- energy: `-7.797909682469515 Ha`
- FCI error: `0.0009334770328921493 Ha`
- parameters: 15
- CNOT count: 107
- CNOT depth: 30

環境:

- Python 3.10.19
- NumPy 1.23.5
- SciPy 1.10.1
- Qiskit 0.43.3
- PySCF 2.2.0
- OpenFermion 1.5.1
- OpenFermion-PySCF 0.5

### 2.2 Baseline保護

公式baselineは新repository内でread-only vendor/submoduleとしてcommitをpinする。
baseline sourceへ直接変更を加えない。新方式はadapter、observer、checkpoint cloneによって接続する。

CIは毎回、vendor tree digestとcanonical filesのdigestを検証し、変更があればfailする。

### 2.3 Baseline parity gate

LiHの前に最低限H2 smokeを通し、LiHでは次を完全比較する。

- energy trajectory
- selected ansatz indices
- coefficients（許容誤差をmanifest化）
- ADAPT iteration
- optimizer counters
- CNOT count/depth trajectory
- first chemical-accuracy crossing
- final statevector digestまたはfidelity

107 CNOT、depth 30、15 parametersへ値を合わせるためにコードや停止条件を調整してはならない。
差が出た場合は差分artifactを保存し、baseline parityが解決するまで新方式を実行しない。

## 3. 研究質問と成功条件

### 3.1 Primary question

同一のDVG_CEO parent checkpointから開始し、accuracyを維持したまま、
CEO blockの削除または安全な再parameter化によって実回路資源をPareto改善できるか。

### 3.2 Primary accuracy gate

first-accuracy比較では、圧縮後も

`abs(E_new - E_FCI) < 1 kcal/mol`

を満たすことを必須とする。FCI energyは評価用であり、candidate受理には使わない。
candidate受理はbaseline energyに対する事前登録local budgetとKKT条件で判定する。

### 3.3 Circuit success

成功は、同一accuracyで以下の少なくとも一つを厳密改善し、他のprimary resourceを悪化させない
Pareto改善とする。

- CNOT depth
- CNOT count
- parameter count
- logical CEO block count

LiHの探索目標は「107 CNOT / depth 30 / 15 parametersより小さい値を少なくとも一軸で得る」
とする。これは性能保証ではなく、未達結果も全て保存する。

### 3.4 Cost success

回路が減っても、無制限の再最適化で得た改善は隠さない。以下をbaseline work、compression work、
total workに分けて報告する。

- energy evaluations
- gradient vector/component evaluations
- optimizer iterations
- statevector kernels
- wall time
- screening/selection work
- circuit executions、shots（将来のfinite-shotのみ）

## 4. 新アルゴリズムの範囲

### 4.1 Core-A: DVG-aware OBS circuit compression

最初に完成させる範囲は回路圧縮だけとする。

- OVP block deletion
- MVP constituent deletion
- MVP whole-block deletion
- MVPからOVP±へのnative reparameterization
- MVPからsingle QEへのreparameterization
- 複数blockのjoint deletion（互いにsemantic conflictがない場合）

順序変更、block merge、global compilationはCore-Aへ含めない。

### 4.2 Core-B: measurement reuse

Core-Aをfreezeした後、別ablationとして追加する。

- OGM-aware measurement reuse
- StatePreparationID / ProblemID / MeasurementContextIDの三層identity
- exact-statevector kernel reuseとpaper-equivalent measurement costを混同しないledger

Core-BはCNOT/depth/operator削減の原因として主張しない。

## 5. 数学仕様

### 5.1 Source quadratic model

source parameterを `theta`、gradientを `g`、近似逆Hessianを `M ~= H^-1` とする。
構造変換はsource-space constraint `A theta = b` と、target-native座標写像

`theta_source = c + J phi_target`

の両方で定義する。`A J = 0` と `A c = b` を機械検証する。

### 5.2 Prediction referenceを分離

次を別fieldとして保存する。

- `predicted_constraint_penalty`
- `predicted_change_from_current`
- `actual_change_from_current`
- `actual_constraint_penalty`
- `reference_energy_kind`

`r = A(theta - M g) - b` としたとき、constraint penaltyは

`P = 1/2 r^T (A M A^T)^-1 r`

current checkpoint基準の二次予測は

`DeltaE_current = -1/2 g^T M g + P`

とする。異なるreferenceの量を直接calibrationしない。

### 5.3 Target-native inverse Hessian

SVD null-space basisをoptimizer座標として使用しない。target Jacobian `J`をcanonicalに定義し、

`M_target = (J^T M_source^-1 J)^-1`

をsolveで計算する。

Jacobianには以下を固定する。

- source slot order
- target slot order
- generator normalization
- OVP± orientation
- sign
- offset `c`
- units

SVD/QR null-spaceはrank検査と `A J = 0` の検証補助に限定する。

### 5.4 Numerical policy

- inverseを明示形成せずCholesky/solveを使う。
- symmetry、SPD、condition number、solve residualを検査する。
- regularizationなしのfail-closedをprimaryとする。
- regularizationは別ablationでのみ許可する。
- toleranceを単位別に分離する。
- negative predicted energyの丸め許容値をHartree単位で定義する。

## 6. DVG-aware Block IR

DVG_CEOはgradientに応じてOVPまたはMVPを選択するため、各actual ansatz blockを実行時に分類する。

各blockは最低限次を持つ。

- block ID
- ADAPT iteration / TETRIS layer
- generator family: OVP / MVP / single-QE
- constituent QE IDs
- source pool indices
- native parameter slots
- generator digest
- support qubits
- normalization/orientation
- circuit implementation ID
- source-to-target Jacobian候補
- symmetry quantum numbers

候補IDは、problem IDではなく構造と数値contextを適切に分けて作る。
候補適用後はactual full ansatzを再構築し、論文と同じcounterでresourceを再計測する。

## 7. Hessianとcheckpoint品質

品質を次の二層に分ける。

### 7.1 Numerical Hessian quality

- finite
- symmetry residual
- positive definiteness
- condition number
- valid BFGS update count
- Hessian age
- internal secant residual
- multi-pair/held-out secant residual
- secant direction coverage

### 7.2 Checkpoint optimality

- optimizer status/message
- gradient L2/RMS/infinity norm
- projected gradient L2/RMS/infinity norm
- KKT residual
- parameter step norm
- energy change in final iterations

`optimizer.success`単独で予測またはcommitを決めない。ただしstatusを無視せず、再検査または事前登録fallbackのtriggerにする。

## 8. Transactionと承認

各compression attemptは次のtransactionで実行する。

1. algorithm/state/ansatz/parameters/Hessian/counters/RNGをsnapshot
2. candidateとJacobianの意味論検証
3. Hessian qualityとprediction
4. target-native warm startを構成
5. transformed full circuitを構築してresource recount
6. 事前登録optimizerで一度再最適化
7. 必要なら事前登録fallbackを最大一回
8. independent energy、constraint、KKT、resourceを検査
9. commitまたはbitwise-equivalent rollback

受理条件:

- finite output
- actual local energy budget以内
- chemical accuracyを維持
- native parameterizationでconstraintを構造的に満たす
- projected gradient/KKT tolerance以内
- state/energy独立再評価一致
- CNOT/depth/parameter/blockのPareto非劣性と一軸以上の改善
- full resource recount成功

optimizer statusがfalseでも自動受理しない。KKT検査と一回のfallback後にのみ判断する。

## 9. 必須ablation

同じcandidate universe、同じaccuracy guard、同じ再最適化上限で比較する。

1. No pruning
2. Magnitude `abs(theta)`
3. Magnitude + ansatz position
4. Diagonal Hessian saliency
5. Single-coordinate OBS
6. General-constraint OBS
7. OBS projectionなし + reoptimization
8. OBS projectionあり + reoptimization
9. Exact Hessian oracle（H2/H4のみ）

candidate rankingとactual outcomeについて報告する。

- Spearman / Kendall correlation
- calibration slope/intercept
- safe-candidate precision/recall
- false-safe rate
- false-reject rate
- resource reduction per reoptimization work
- oracle regret

## 10. Checkpoint比較

次を混同しない。

- `target-accuracy`: first chemical-accuracy crossingで一回圧縮
- `post-hoc`: terminal convergence後に一回圧縮
- `online`: 各ADAPT iterationまたは固定間隔で圧縮

primaryは`target-accuracy`とする。post-hocとonlineは別ablationであり、primary結果を見て切り替えない。

## 11. 実装ステップとDefinition of Done

### S0: Repository isolationとpre-registration

- 新Private repositoryを作る。
- 旧V2をdependency graphから排除する。
- upstream baseline commitをpinする。
- scientific claim、metrics、accuracy、checkpoint、holdoutをmanifest化する。
- branch protection、PR review、signed/annotated stage tag方針を定義する。

DoD: dependency scanで旧V2 import/copyが0件。baseline vendor digestが固定。

### S1: Baseline wrapperとparity

- baselineを変更しないobserver/adapterを新規実装する。
- H2 smokeとLiH canonical reproductionを実行する。
- trajectory、operator sequence、resource、environmentを保存する。

DoD: canonical tolerance内でLiH 107 CNOT / depth 30 / 15 parameters / iteration 5を再現。

### S2: 新telemetry・identity・schema

- StatePreparationID、ProblemID、MeasurementContextIDを新schemaで実装する。
- event ledger、resource snapshot、optimizer diagnosticsを実装する。
- schema versionとmigration禁止方針を定義する。

DoD: round-trip、tamper、cross-context reuse拒否testが通る。

### S3: Mathematical kernelとproperty tests

- prediction referenceを分離する。
- constraint＋target Jacobian IRを実装する。
- target-native inverse Hessianを実装する。
- randomized SPD quadratic property testsを作る。

必須test:

- coordinate deletion
- multiple deletion
- `theta1 = theta2`
- `theta1 = -theta2`
- nonzero gradient
- slot permutation/sign/basis rotation
- ill-conditioned rejection
- analytic Newton direction一致

DoD: constrained optimum、penalty、target Hessian、Newton directionが解析解と一致。

### S4: DVG block introspectionとcandidate catalog

- actual DVG ansatzをOVP/MVP/QE blockへ復元する。
- block deletion、constituent deletion、MVP→OVP±、MVP→QEを生成する。
- symmetry、support、orientation、slot mappingを検証する。

DoD: source/target generator、unitary、random-state outputが規定誤差内で一致。

### S5: Hessian captureとquality diagnostics

- BFGS更新を追加evaluationなしでcaptureする。
- internalとheld-out secantを分離する。
- L2/RMS/infinity gradientとKKTを保存する。

DoD: capture OFF/ONでbaseline trajectoryとwork counterが一致。

### S6: Full-circuit resource evaluator

- candidate単独・joint適用後のfull ansatzを再構築する。
- paper-era counterと同じ定義でCNOT/count/depthを数える。
- arbitrary barrier-free global transpilationは追加しない。

DoD: baseline OFF時の全resource trajectoryがcanonical runと一致。

### S7: Transaction、KKT acceptance、rollback

- snapshot/commit/rollbackを実装する。
- optimizer status、KKT、energy、constraint、resourceを独立判定する。
- crash injection、NaN、timeout、partial artifact writeをtestする。

DoD: 全failure injection後にstate・Hessian・counters・artifactsが矛盾なく復元。

### S8: Predictor calibration harness

- H2/H4の小系で全候補を評価する。
- unconstrained/constrainedを同一optimizer条件で比較する。
- magnitude、position、diagonal Hessian、OBS、exact Hessianを比較する。

DoD: 全候補CSV、散布図、classification metrics、work ledgerが生成される。

### S9: Candidate selector freeze

- accuracy budgetをconstraintとし、resourceをlexicographic/Pareto選択する。
- batch size、shortlist、fallbackをH2/H4だけで決める。
- trust-regionを使う場合は更新式、上下限、停止条件を事前登録する。

DoD: LiH実行前にselector config digestをimmutable tagで固定。

### S10: LiH paired execution

- canonical iteration-5 checkpointを一度生成する。
- exact cloneからNo-pruningとDVG-OBS-CEOを分岐する。
- first-accuracy primary、terminal/onlineは別run IDで実行する。
- 全rollback・retry・workを保存する。

DoD: comparison bundleがschema検証を通り、失敗を含む全trialが残る。

### S11: 通常ADAPT / CEO* / 新方式の比較

- normal GSD-ADAPTは論文設定または再現可能設定を明記する。
- CEO*はcanonical direct runを使用する。
- 新方式は同じCEO* checkpointからのpaired comparisonを主因果比較とする。

出力:

- energy/error vs ADAPT iteration
- energy/error vs wall time
- energy/error vs energy/gradient evaluations
- CNOT、depth、parameters、blocks vs iteration/time/work
- predicted vs actual loss
- baseline/compression/total work
- Pareto fronts
- paper Fig. 11/14/15相当。ただしmeasurement cost未校正panelは生成拒否。

DoD: 同一条件列と非同一条件列が機械的に区別される。

### S12: Measurement reuse extension

- Core-Aをtag/freezeしてから別branchで開始する。
- OGM-aware reuseを追加し、circuit reductionとの因果を分離する。
- paper-equivalent measurement costはTable 1再現後だけ表示する。

DoD: reuse OFFでCore-A artifactが一致し、reuse ON/OFFのmeasurement ledger差が説明可能。

## 12. Git/GitHub運用

- GitHub repositoryは最初からPrivate。
- `main`は保護し、stageごとにfeature branchとPRを作る。
- stage完了時にtests、artifact manifest、decision logをcommitする。
- tag例: `dvg-obs-s0`, `dvg-obs-s1-baseline-parity`。
- 大きなraw artifactはGit LFSまたはrelease bundleへ分離し、manifestとSHA-256だけをGit管理する。
- 実験後のthreshold変更は既存manifestを編集せず、新protocol versionを作る。
- force push、履歴改変、artifact上書きを禁止する。

## 13. Stop/Go gates

- Gate A: baseline parity未達ならS2以降へ進まない。
- Gate B: Jacobian/property test未達なら分子simulationへ進まない。
- Gate C: rollback test未達ならcandidateを実baselineへ適用しない。
- Gate D: H2/H4 calibration未完了ならLiH selectorをfreezeしない。
- Gate E: LiH後にthresholdを変更した場合、同じ結果をvalidation claimに使わない。
- Gate F: measurement-cost定義未再現なら`measurement cost unavailable`と表示する。

## 14. 学術的なclaim boundary

以下を区別する。

- 数式が解析的二次問題で正しい。
- 実装がproperty testに合格した。
- predictorが実分子でcalibratedである。
- OBSがmagnitude baselineより優れる。
- CEO*より同一accuracyで回路資源が少ない。
- total measurement/workまで少ない。

一つの成立から次を自動的に主張しない。LiHは既に観測済みであるためblind holdoutとは呼ばない。
将来の性能一般化には、設定freeze後のH6またはBeH2など未使用系を別途必要とする。

## 15. 最初に作る成果物

実装開始時の順番を固定する。

1. 新Private repositoryとbaseline pin
2. `PREREGISTRATION.md`
3. baseline manifestとparity report
4. mathematical specification
5. target Jacobian IR schema
6. randomized quadratic property tests
7. DVG block schema

この7点が揃うまで、LiHに対するpruning実行コードは作らない。
