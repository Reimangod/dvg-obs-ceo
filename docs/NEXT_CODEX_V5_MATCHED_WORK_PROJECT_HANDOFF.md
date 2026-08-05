# Next Codex handoff: V5 matched-work robustness study

## 0. この文書の目的

この文書は、次のCodexが新しい独立プロジェクトでV5のmatched-work、
sequential catalog rebuilding、source sensitivity、outcome-unseen validationを
検証するための引継ぎ仕様である。

これは既存の`pra-critical-path`を再開する計画ではない。既存計画はS6の
cross-system gateで停止し、S7--S9を未承認として閉じ、S11でnegative-result
releaseを公開済みである。新しい結果を既存計画へ追加したり、既存のdevelopment
結果をprospectiveへ改称してはならない。

この計画は性能向上を保証しない。中心目的は、V5の改善が追加探索量や特定の
CEO* sourceに由来するのか、それとも逐次catalog再構築に再現可能な追加価値が
あるのかを、同じsourceと事前固定work envelopeで判定することである。

## 1. 次のCodexへの最初の指示

次の文章を新しいCodex taskの冒頭指示として使用する。

> このhandoff文書を最初から最後まで読み、記載された証拠境界と禁止事項を
> 守って、新しい独立repositoryを構築してください。S0終了後に監査し、Goなら
> S1へ進む形式で自動的に進めてください。ただし、performance outcomeを見る
> stageの前には必ずprotocol、queue、work cap、success条件をcommit/tagして
> ください。既存artifactを書き換えず、失敗・棄却・rollback・no-candidateを
> 保存してください。ゲート失敗時はdependent stageを実行せず、NOT_AUTHORIZED
> artifactを作ってfail-closedで終了してください。推測で重要条件を決めず、
> 公式論文、補足資料、公開コードまたはlocal evidenceで確認してください。

## 2. 出発点

### 2.1 既存repository

- GitHub: `https://github.com/Reimangod/dvg-obs-ceo`
- branch: `pra-critical-path`
- immutable tag: `pra-critical-path-negative-result-v1`
- peeled commit: `4783b9ff9f9b6f2061a1ef8c02613f4c6cef38db`
- upstream CEO* submodule commit:
  `a3f89d03e6a03c89767d3cf8ee7657a57653dda0`
- Python constraint: `>=3.10,<3.11`
- dependency freeze: `uv.lock`

### 2.2 新プロジェクトの提案名

- local: `/Users/rei/Documents/ceo-adapt-vqe/v5-matched-work-study`
- GitHub: `Reimangod/v5-matched-work-study`
- initial visibility: private

上記は提案値であり、作成時に実在確認する。既存repository内へ新しいperformance
artifactを書き足さない。

### 2.3 推奨する分離方法

新repositoryを空のGit履歴から開始し、既存repositoryをread-only provenance
sourceとして固定する。次のどちらかを選び、その選択をS0で記録する。

1. 既存repositoryをGit submoduleとして上記tag/commitへpinする。
2. 必要コードだけをlicenseと元commitを保存して移植し、file manifestとSHA-256を
   記録する。

方法1を推奨する。どちらの場合も、旧`artifacts/`を新しい結果ディレクトリへ
コピーして新規結果に見せてはならない。

## 3. 既に分かっている事実

### 3.1 V4.1とV5の計算量は一致していない

| Case | V4.1 search states / exact attempts | V5 expanded states / exact attempts |
|---|---:|---:|
| LiH 3.0 A | 168 / 2 | 877 / 6 |
| H6 1.5 A | 10,000 / 4 | 26,010 / 4 |
| H6 3.0 A | 10,000 / 4 | 45,273 / 6 |
| BeH2 3.0 A | 10,000 / 4 | 16,295 / 4 |

したがって、既存H6 3.0 AのV5改善はbest-found development resultであり、
matched-work superiorityではない。

### 3.2 V5の実装上の中心

V5はaccepted compression後にblock、candidate、curvature coordinates、resourceを
再構築し、bounded Pareto beamを維持する。中心実装は
`src/dvg_obs_ceo/v5_multitrajectory.py`の`run_multitrajectory`である。

中心仮説は「V5が常に最良」ではなく、次に限定する。

> 同一のstationarity-normalized CEO* sourceと同一のcomponentwise work envelope
> の下で、逐次catalog再構築を含むV5が、再構築なしのV5およびone-shot V4.1に
> 存在しないenergy--physical-resource非支配点を複数の独立条件で追加する。

### 3.3 既存V5の既知問題

- historical multisystem acceptanceにFCI-derived marginが含まれた。
- raw winner orderingはresource-firstで、energyは後順位である。
- V4.1とV5でsearch/exact workが不一致である。
- H6とBeH2の一部探索はbudget-truncatedである。
- production uncertainty marginは`0.0`であり、名称ほどrisk penaltyが働かない。
- 旧artifactの一部でendpoint provenance labelの誤りがあった。
- stationarity failureがhard threshold近傍へ集中する条件がある。
- parameterを0にしてもCEO blockが残る場合、物理CNOT/depthは減らない。

これらを隠したり旧artifactから削除してはならない。新プロジェクトでは、結果を
見る前にcorrectness baselineを作り、修正前後を別versionとして記録する。

### 3.4 分子依存性

- LiH 3.0 A: audited sourceにMVP blockがなく、V4.1が構造floorへ到達した。
- H6 1.5 A: 初回圧縮後、後続候補が`1e-8` stationarity閾値付近で失敗した。
- H6 3.0 A: catalog rebuildingが継続して候補を露出したが、V5のworkが多い。
- BeH2 3.0 A: 最初の圧縮でenergy budgetの約98.5%を消費し後続余地が小さい。

この差は、単一の分子非依存thresholdだけで安定性能を保証できないことを示す。

### 3.5 閉じたPRA critical-pathの結果

- H4 1.0 A: 8候補中7候補をcertify。
- H4 2.0 A: 8候補中7候補をcertify。
- H5 1.5 A: 8候補すべてnon-certified。
- H5候補はenergy、semantic、native resourceを通過したが、200 iteration capと
  coordinate-invariant tangent stationarityを通過しなかった。
- S7 matched-work、S8 prospective freeze、S9 prospective runは実行していない。
- このnegative resultは新計画のdevelopment evidenceでありprospectiveではない。

## 4. 学術的な境界

### 4.1 許可される主張

- V5が固定CEO* checkpointを後処理するcompression methodであること。
- 特定のdevelopment conditionでphysical-resource reductionを得たこと。
- matched-work、source sensitivity、prospective testを実行した場合の限定的結果。
- negative、null、no-candidate、optimizer failureを含む条件別結果。

### 4.2 証拠なしに禁止される主張

- V5が全分子で最良または安定して最良である。
- V5が通常ADAPTやCEO*よりend-to-endで低コストである。
- best-found結果をmatched-work superiorityと呼ぶ。
- parameter reductionをphysical circuit reductionと呼ぶ。
- H2O/N2を既存PRA計画のprospective結果と呼ぶ。
- exact noiseless simulator結果からhardware/noise優位性を主張する。
- 異種work counterをCEO論文のMeasurement Costと呼ぶ。
- internal Go/No-Go値をPRA公式採択基準と呼ぶ。

### 4.3 FCIの使用

FCIまたはexact reference energyはoffline reportingだけに使用する。candidate選択、
energy budget、停止、winner selection、rerun判断に使用しない。

## 5. Scientific identity

最低限、以下を分離して保存する。

### StatePreparationID

- reference state
- generator-definition digest
- ansatz block structure
- ansatz indices
- canonical coefficient bytes
- orbital parameters
- qubit mapping
- qubit ordering

### ProblemID

- Hamiltonian digest
- molecule and exact geometry
- charge and multiplicity
- basis set
- active space
- frozen orbitals
- fermion-to-qubit convention

### MeasurementContextID

- StatePreparationID
- ProblemID
- observable-set digest
- measurement-plan version
- grouping strategy
- estimator version
- backend context

measurement-plan versionは量子状態を定義しないためStatePreparationIDへ入れない。
今回はexact noiseless statevector regimeをprimary scopeとする。

## 6. Work accounting

各method、candidate、accepted/rejected/rollback pathについて次を保存する。

\[
W=(N_E,N_G,N_{\mathrm{gradcomp}},N_{\mathrm{HVP}},
N_{\mathrm{exact}},N_{\mathrm{recount}},N_{\mathrm{rewrite}},
N_{\mathrm{states}},N_{\mathrm{rounds}}).
\]

- `N_E`: scalar energy evaluations
- `N_G`: full gradient-vector evaluations
- `N_gradcomp`: component-equivalent gradient evaluations
- `N_HVP`: Hessian-vector products
- `N_exact`: exact optimized candidate attempts
- `N_recount`: full physical circuit recounts
- `N_rewrite`: exact algebraic rewrites attempted
- `N_states`: unique search states expanded
- `N_rounds`: sequential accepted/attempted rounds

異種成分を恣意的な重みで一つのscalar costへ足さない。LOW/MEDIUM/HIGHは全成分の
数値上限としてfreezeし、次のoperationがどれか一つのcapを超える場合は開始しない。
wall time、peak RSS、CPU model、thread countはsecondary engineering metricとして記録する。

CEO論文のMeasurement Costを同じ定義で再構成できない場合は`null`とする。

## 7. 必須comparatorsとablation

### Primary

1. immutable CEO* source
2. same-structure reoptimization
3. structural magnitude pruning
4. V4.1 one-shot joint compression
5. V5 sequential execution without catalog rebuilding
6. full V5 with catalog rebuilding

### Secondary

7. V5 + V5.1 exact fusion（registered candidateが存在する場合のみ）
8. external end-to-end baseline（中心仮説通過後のみ）
9. hardware-mapped reporting（中心仮説通過後のみ）

V5.1 exact fusionはV5 rebuildingの因果効果と混ぜず、別のcompositional ablationと
する。`not applicable`を失敗やゼロ改善へ置換しない。

### Magnitude baselineの注意

次を区別する。

- coefficientを0にしただけのstate/optimization control
- generator/operatorを物理削除したstructural pruning
- block再構築・再最適化・full-circuit recount後の物理resource

zero coefficientだけでCNOT/depth削減を記録してはならない。

### Same-structure controlの役割

stationary sourceに同一構造再最適化を行う。大きなenergy improvementが出た場合は、
compression成功ではなくsource stationarity、optimizer equivalence、identity mismatchの
incident候補として扱う。

## 8. 段階別実行計画

## S0 — repository isolation and immutable import ledger

### 作業

- 新しいprivate repositoryを作る。
- parent tag/commit、CEO* submodule commit、`uv.lock` digestを固定する。
- importするcode/fileをmanifest化する。
- 旧結果を`historical-development`としてhash登録する。
- 新しい`artifacts/`、`schemas/`、`tests/`を空から作る。
- destructive overwriteを禁止するatomic artifact writerを用意する。

### 監査

- clean cloneから同じcommit/submodule/digestを復元できる。
- 旧artifactはread-onlyで、新artifact namespaceと分離される。
- GitHub visibility、branch protection、tag policyを記録する。

### Gate

再現可能な分離ができなければS1へ進まない。

## S1 — V5 correctness baseline

### 作業

- historical V5挙動を変更せずreplayする。
- FCI-derived online marginを除去し、source-relative budgetへ統一する。
- primary outputを単一resource-first winnerではなく全accepted Pareto frontierにする。
- endpoint provenanceをruntime sourceから直接保存する。
- uncertainty marginが0なら「risk-aware improvement」を主張しない。
- candidate/full-source/tangent gradientの名称を分離する。
- transaction、rollback、parent immutabilityを検査する。

### Gate

- historical replay差が説明される。
- outcome-independent correctness修正だけである。
- candidate orderを変える修正はscientific changeとして別version化される。
- 全回帰テストとproperty/invariant testが通る。

## S2 — stationary source protocol

### 固定項目

- molecule geometry、basis、active space、mapping、ordering
- CEO pool、TETRIS/selection、stopping rule
- source optimizer、fallback、seed
- parameter stationarityとpool-gradient stoppingを別々に保存
- resource counter、compiler-independent logical circuit definition

### 必須証拠

- `||grad_theta E||_infinity <= 1e-8`を初期候補とするが、finite-difference agreementと
  数値精度を既存development dataだけで監査してからfreezeする。
- source energy、statevector、coefficients、structure、Hamiltonianのdigest
- full source resource recount

thresholdを新しい分子の結果を見て緩和しない。

## S3 — work-ledger schema and accounting calibration

### 作業

- 全work counterの意味、単位、increment locationを定義する。
- rejected、failed、duplicate、rollbackも消費workへ含める。
- cache hit/missとmeasurement/statevector reuseを分離する。
- LOW/MEDIUM/HIGHの具体的数値capを既存development dataだけで固定する。
- process countやparallel orderでcanonical結果が変わらないことを検査する。

### Gate

- independent auditがraw event logから全counterを再構成できる。
- comparator間で同名counterが同じ操作を意味する。

## S4 — comparator implementation

各primary comparatorを同じimmutable source interfaceへ接続する。

- V4.1へV5固有の追加roundを与えない。
- 各methodを本来の規則で実行し、共通capで止める。
- `V5 without rebuilding`ではaccepted child後もoriginal catalog snapshotを使い、
  full V5だけがcatalogを再構築する。
- source、candidate、final full-circuit resourceを同一counterで再計測する。
- semantic/native state fidelity、energy、stationarityを独立計算する。

### Gate

toy/H2/H4で、cap enforcement、rollback、deduplication、recount、determinismが通る。
このstageのtoy結果を分子性能主張へ使わない。

## S5 — development protocol freeze

### Development conditions

- LiH 3.0 A
- H6 1.5 A
- H6 3.0 A
- BeH2 3.0 A
- H4の既知geometry

全て既知developmentでありprospectiveではない。

### Freezeするもの

- source selection rule
- exact work caps LOW/MEDIUM/HIGH
- comparator set
- candidate orderingとtie-break
- optimizerと全fallback
- energy/stationarity/semantic/resource tolerance
- Pareto definitionとdominance tolerance
- failure、rerun、incident policy
- primary figuresとsummary statistics
- Go/No-Go

manifestをcommitし、annotated tagを作るまでS6を実行しない。

## S6 — existing-system matched-work evaluation

### 実行

全development conditionについて、全primary comparatorを同じsourceから実行する。
順序はfreezeし、失敗しても次条件の設定を変えない。

### Primary outputs

- energy loss vs CNOT
- energy loss vs CNOT depth
- energy loss vs total depth
- energy loss vs parameter count
- cumulative componentwise work vs resource reduction
- context-level nondominated-point indicator
- accepted/rejected/no-candidate/stationarity-failure counts

### Go

少なくとも2つの独立development contextで、同じwork envelope内のfull V5がV4.1に
ない非支配点を追加し、少なくとも1 contextで`without rebuilding`にない点を追加する。

### No-Go

- V4.1との差がwork matching後に消える。
- full V5とwithout rebuildingに差がない。
- positiveが追加reoptimizationだけで説明される。
- certification failureまたはartifact corruptionが未解決である。

No-GoならS7以降を実行せず、negative-result packageを作る。

## S7 — source sensitivity pilot

S6 Goの場合のみ実行する。

### 設計

- 圧縮しやすい既知条件1つとMVP-heavy条件1つを選ぶ。
- 各条件で最低3本の事前定義trajectoryを作る。
- seed、tie-break、initial condition、deterministic perturbationをmanifest化する。
- 「微小な数値差」を人為的に選ばない。

3本ではrobustnessの統計的証明と呼ばず、sensitivity pilotと呼ぶ。

### Outputs

- context/trajectoryごとのfrontier
- CNOT/depth/parameter reductionのmedian、range、raw values
- accepted round、新規candidate、no-candidate、stationarity failure
- source topology descriptors

### Gate

一つのtrajectoryだけの成功なら「stable」主張を禁止する。追加本数は結果を見た後に
恣意的に増やさず、別の事前登録replicationとする。

## S8 — outcome-unseen validation freeze

S6 GoかつS7で単一trajectory依存が否定された場合のみ実行する。

### 第一候補

H2Oのexactly specified 2 geometries。ただし、次を結果取得前に固定する。

- Cartesian coordinatesとunit
- equilibrium/stretchの数値
- charge、multiplicity、basis
- active-space electrons/orbitals、frozen orbitals
- mapping、ordering、qubit count
- statevector feasibility上限
- source generation protocol
- structural applicability rule
- molecule exclusion/fallback rule

H2Oは既存PRA計画のprospective caseではなく、新studyのoutcome-unseen validationと
記載する。分子候補自体が過去議論で選定済みであることも開示する。

### Freeze

- code commitとcontainerまたは完全lockfile
- input manifest
- candidate queue生成規則
- LOW/MEDIUM/HIGH cap
- comparators
- two-geometry joint reporting rule
- rerun/incident policy
- success条件

tag前にcandidate energyを評価しない。

## S9 — H2O one-time validation

- 2 geometriesを固定順で一度ずつ実行する。
- 一方が失敗してももう一方を隠さない。
- engineering defect rerunはincident、partial artifact、fix commitを先に公開する。
- scientific threshold、optimizer、catalog、budgetは変更しない。

最低内部gateは、2 geometry中少なくとも1つでmatched-work nondominated pointを追加し、
両方を完全報告すること。ただし1/2だけで「general robustness」とは主張しない。

## S10 — optional N2 replication

H2O結果を見てもprotocolを一切変更せず、かつ事前に固定したsmall active spaceで
feasibleな場合のみ実行する。

- exact Cartesian/internal geometry
- active space
- equilibrium/stretch distance
- resource limitとtimeout

をS8時点で固定する。H2O後にN2設定を変えた場合、N2は新しいdevelopment studyに
なる。

## S11 — conditional external baseline

中心仮説がS6/S9を通過した場合のみ行う。

- Pruned-ADAPT-VQEを第一候補とする。
- source後処理比較ではなくend-to-end secondary comparisonとする。
- 公式paper、supporting information、公開code、licenseを確認する。
- Hamiltonianだけでなくactive space、mapping、accuracy criterion、work definitionを
  対応づける。
- 再現できない項目を推定値で埋めない。

## S12 — conditional hardware mapping

logical native-circuit結果をprimaryのまま維持し、mappingはsecondary reportingとする。

- exact coupling graph
- basis gates
- transpiler/compiler version
- optimization level
- layout policy
- seed set
- routing後CNOT/depth/SWAP
- pre/post transpilation stateまたはunitary equivalence audit

barrier-free full-ansatz compilationをV5アルゴリズムの一部として追加しない。

## S13 — integrated scientific audit

### Primary statistics

- context success rate（candidate単位ではない）
- medianと全raw resource reduction
- worst case
- no-candidate rate
- stationarity-failure rate
- energy-budget utilization
- matched-work frontier contribution

小標本でconfidence intervalを過大解釈しない。deterministic simulator resultとsource
sensitivity distributionを区別する。

### Causal questions

1. additional reoptimizationだけで説明できるか。
2. V4.1より多いworkだけで説明できるか。
3. rebuildingなしとの差があるか。
4. source topology/trajectoryへ過度に依存するか。
5. exact fusionを除いてもV5効果が残るか。

### Editorial boundary

PRA向けperformance packageへ進むかは、novelty、effect size、cross-context consistency、
matched-work、outcome-unseen evidence、mechanism ablation、reproducibilityを総合評価する。
内部数値gateをPRA公式基準として記載しない。

## S14 — reproducible release

- source、input、queue、event log、accepted/rejected/rollback artifact
- schemaとfield dictionary
- case-level、attempt-level、work-level CSV
- figure generation script
- environment lock/container digest
- full test commandと結果
- artifact SHA-256とinternal digest audit
- code/data availability statement
- null/negative/no-candidate appendix
- claim-boundary document
- annotated release tag

clean cloneからtable/figureを再生成し、GitHub releaseを作る。Zenodo DOIは実際にmint
した場合だけ記載する。

## 9. Engineering safety requirements

- artifactはatomic exclusive createで公開しoverwriteを拒否する。
- stage開始時にclean worktree、commit、submodule、environmentを記録する。
- performance runはpre-outcome tagからだけ開始する。
- source objectはimmutable cloneとbefore/after digestで保護する。
- candidate failureはparentへcommitせず完全rollbackする。
- NaN/Inf、partial files、duplicate IDs、missing queue itemsをfail closedにする。
- queue itemはexactly onceを監査する。
- cache keyはStatePreparationID、ProblemID、observable/contextを混同しない。
- parallel executionでもcanonical orderingとresult digestが一致するようにする。
- timeout、SIGTERM、disk-fullを模擬したtransaction testを用意する。
- userの既存変更を上書きしない。
- force-push、tag rewrite、artifact replacementを禁止する。

## 10. 各stage共通の完了条件

各stageは最低限、次を揃える。

1. human-readable protocol/result MD
2. machine-readable immutable JSON
3. JSON Schemaまたは同等のstrict validator
4. unit/integration/invariant tests
5. independent result audit
6. clean Git commit
7. annotated tag
8. Go/No-Goと次stage authorization
9. claim boundary
10. negative/null/failed recordsの保持

## 11. 最初に読むlocal evidence

新しいCodexは、実装前に最低限以下を完全に読む。

- `docs/VERSION_BEHAVIOR_AND_MOLECULE_DEPENDENCE_AUDIT.md`
- `docs/V5_RISK_AWARE_SEQUENTIAL_PLAN.md`
- `docs/V5_V5_1_RELEASE_RESULT.md`
- `docs/PRA_CRITICAL_PATH_PLAN.md`
- `docs/PRA_CRITICAL_PATH_S6_RESULT.md`
- `docs/PRA_CRITICAL_PATH_S11_RELEASE.md`
- `src/dvg_obs_ceo/v5_multitrajectory.py`
- `src/dvg_obs_ceo/v5_protocol.py`
- `src/dvg_obs_ceo/v5_1_exact_fusion.py`
- V4.1/V5/V5.1のrunnerとindependent audit
- `artifacts/pra_path/release/negative-result-release-manifest-v1.json`

ファイルが見つからない場合は推測せず、`rg --files`で正確な位置を確認する。

## 12. 外部文献確認

最低限、以下のprimary source、supporting information、公開codeの有無を確認する。

- CEO-ADAPT-VQE*: `https://doi.org/10.1038/s41534-025-01039-4`
- Pruned-ADAPT-VQE: `https://doi.org/10.1021/acs.jctc.5c00535`
- Param-ADAPT-VQE: `https://doi.org/10.1021/acs.jctc.6c00269`
- Circuit-Efficient QEB-VQE: `https://doi.org/10.1021/acs.jctc.5c00119`
- Physical Review A scope: `https://journals.aps.org/pra/about`

論文タイトルやabstractだけで、geometry、active space、数値削減率、コード挙動を
確定しない。本文、補足資料、repository commitを確認して引用台帳へ保存する。

## 13. コストを抑える停止規則

1. S0--S4のcorrectness/infrastructureが通らなければ分子計算を開始しない。
2. S6 matched-workでV5差が消えたらH2O/N2を実行しない。
3. rebuilding ablationがnegativeならV5の中心主張を終了する。
4. source sensitivityが単一trajectory依存ならprospectiveを延期する。
5. H2Oでnegativeでも結果を保持し、設定変更なしN2が事前承認済みの場合だけ続ける。
6. external baselineとhardware mappingは中心仮説が成立した後だけ行う。

この順序により、最も高価な未知分子計算の前に、既存条件だけで中心仮説を棄却できる。

## 14. 最終的な成功の意味

成功とは、全分子でV5をwinnerにすることではない。次を同時に示すことである。

- 同じstationary sourceを使用した。
- 同じcomponentwise work envelopeを使用した。
- rejected/failed workも計算量へ含めた。
- V5 rebuildingがwithout-rebuildingとの差を生んだ。
- 複数development contextで新しいPareto点を追加した。
- outcome-unseen conditionでも少なくとも限定的に再現した。
- 結果が一つのsource trajectoryだけに依存しない。
- physical CNOT/depthをfull circuitから再計測した。
- negative resultと適用不能条件を保持した。

これを満たさない場合でも、原因を分離した完全なnegative-result studyとして閉じる。
