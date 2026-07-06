# 学習フレームワーク主役化の設計案（関連研究調査 + データ特性に基づく）

作成日: 2026-07-06。`docs/paper_structure.md` の批評を受け、「学習フレームワークを論文の主役とする」場合の設計案を、(1) 手元データの実態、(2) 2026 年央時点の関連研究調査、の両面から導出したもの。

---

## 1. 前提となるデータ特性（実測）

`data/processed/benchmarks_latest_revision.json` と `outputs/jsperf/setup/`（step1: setup+test 結合による実行プログラム化、step2: Node 実行可否スクリーニング）から確認した事実。

| 特性 | 実測値 |
|---|---|
| ユニーク最新 revision ベンチ数 | 23,055（プログラム 77,979 本） |
| Node で実行可能（success） | 43,825 本（56%）。失敗の主因は `window` 等ブラウザ依存の ReferenceError（31k 件） |
| **2 変種以上が実行可能なベンチ** | **13,054 ベンチ / 43,244 プログラム / ペア組合せ 105,634** |
| 変種数の構造 | 2 変種: 6,811 / **3 変種以上: 6,243（48%）**、最大 16+ |
| プログラムサイズ | 中央値 228 バイト、p90 2.7KB — **実行が極めて安価**（78k 本を 35 並列 48 分で実行済み） |
| 年代分布 | 二峰性: 2010–2016（旧 V8 世代）約 9,300 / 2023–2026（現行世代）約 3,400（実行可能ベンチ内） |
| setup の有無 | 約 55% が setup（共有コンテキスト）を持つ |

学習設計に効く含意:

- **D1（リスト構造）**: データは slow/fast の「ペア」ではなく、「同一意図の独立に書かれた等価実装群 + 実測順位」という**リスト**。約半数が 3 変種以上を持つ。
- **D2（連続・ノイズ付き報酬）**: ラベルは再計測で与える ops/sec であり、**連続量 + 信頼区間**が得られる。性能差が小さいペアほど順位が反転しやすい「マージン依存ノイズ」を持つ。
- **D3（安価な実行オラクル）**: プログラムが極小のため、計測基盤をオフラインのラベル付けだけでなく**学習ループ内の報酬オラクル**としても使える。
- **D4（世代の二峰性）**: 旧世代由来の「速い」は現行 V8 で逆転しうる。ラベルは現行環境の再計測から与える必要があり、逆にこの二峰性は「エンジン世代を跨ぐ知識の可搬性」という分析軸になる。
- **D5（テストスイート不在）**: 等価性は差分テスト（多入力比較、大森手法）でしか確認できない。等価性は**ゲート信号**として損失構成に組み込む対象。

---

## 2. 関連研究調査の要点（2026-07 時点）

詳細は調査レポート参照。フレームワーク設計に直結する結論のみ抜粋。

### 2.1 直近の到達点

- **PIE**（ICLR 2024）: 人間の slow→fast 編集ペア（競プロ C++）で SFT + 性能条件付き生成。測定ノイズは gem5 シミュレータで「消す」戦略。
- **ECCO**（EMNLP 2024）: 効率を上げると正しさが落ちるトレードオフを系統的に示した（Python）。
- **Afterburner**（arXiv 2025）: 実行サンドボックスの性能報酬で **SFT / DPO / GRPO を直接比較**。SFT・DPO は早期飽和、**GRPO のみ継続改善**という重要知見。
- **CodeDPO**（ACL 2025）/ **Code-Optimise** / **EffiCoder**（ICML 2025）: 効率指向の選好・SFT 学習はすべて**モデル自己生成解**をデータ源とし、二値ペア選好。
- **Mercury**（NeurIPS 2024 D&B）: 課題ごとに**複数の人間解を実測ランタイム分布として保持**し、そこから DPO ペアを構成（効率化には SFT より DPO が頑健と報告）。**jsPerf 構造に最も近い既存資源**だが、Python/LeetCode の問題解答単位・二値ペア選好であり、listwise・連続マージン・測定不確実性は扱わない。
- **Saiki & Ihara**（SCAM 2021, DOI: 10.1109/SCAM52516.2021.00038）: jsPerf 内の類似スニペット紐付け。**jsPerf の学術利用はこのマイニング研究のみ**で、学習への接続は前例なし。前処理・重複統合の方法論として引用価値あり。
- **SkelDPO**（arXiv 2026-06、査読未確認）: コードレベル + skeleton レベルの二重選好。最も近い対抗馬だが直近プレプリント。
- 選好最適化の部品: **LiPO**（NAACL 2025、listwise + LambdaLoss）、**ODPO**（Findings of ACL 2024、報酬差比例マージン）、**rDPO**（ICML 2024、一様既知ノイズ ε への頑健化）、**GRPO**（グループ内相対アドバンテージ）。

### 2.2 空白地帯（調査で先行研究ゼロと確認された交差点）

- **G1**: JavaScript を対象とする学習ベース性能最適化（学習は C++/C#/Python/CUDA に集中。JS は評価ベンチ EffiBench-X のみ）。
- **G2**: jsPerf / measurethat.net の訓練データ利用（前例 0 件）。
- **G3**: 「独立に書かれた複数等価実装のリスト」からの学習。ただし **Mercury が複数人間解のランタイム分布から二値 DPO ペアを構成する先例**であり、完全な空白ではない。残る空白は「**リスト構造のまま**（listwise）」「**マイクロベンチ・イディオムレベル**（問題解答でなく）」「**JS**」の組合せ。新規性主張は G4/G5 と束ねて行うのが安全。
- **G4**: **実測された物理量（ops/sec）とその測定不確実性**を選好損失のマージン・重みに使う手法（ODPO 等のマージン源は報酬モデルのスコア）。
- **G5**: listwise × 連続実測マージン × マージン依存ノイズの同時取り扱い（LiPO / ODPO / rDPO が別々に存在し交差点は空白）。
- **G6**: テストスイートを持たないデータに対する等価性検証（差分テスト）と学習の統合。
- **G7**: エンジン依存イディオム書き換え（`for` vs `reduce` 等）の学習。既存はアルゴリズム置換が主。

**設計原理: D1↔G3、D2↔G4/G5、D3↔（Afterburner 系の JS 版）、D5↔G6 という 1 対 1 対応があり、「このデータでなければ成立しない学習フレームワーク」を構成できる。これがフレームワーク主役化の根拠。**

---

## 3. 設計案

### 案 A: 計測接地 listwise 選好最適化（本命・オフライン）

**仮称**: Measurement-Grounded Listwise Preference Optimization（MG-LPO）

**核**: 「二値の chosen/rejected」を捨て、jsPerf の素性（等価実装リスト + 実測 ops/sec + 信頼区間）をそのまま損失に写像する選好学習。

1. **listwise 化**（D1/G3）: ベンチ = 1 グループとして LiPO 系 LambdaLoss を適用。ペア分解する場合も同一グループ内の全順序対を使う。
2. **実測マージン注入**（D2/G4）: ペア (i, j) の要求マージンを log(speedup_ij) に比例させる（ODPO の offset を報酬モデルスコアでなく物理実測値で与える初の事例）。10 倍差と 1.05 倍差を等価に扱わない。
3. **不確実性重み付け**（D2/G5）: 信頼区間の重なりから順位反転確率 ε_ij をペアごとに推定し、損失を重み付け（rDPO の一様 ε をヘテロな実測 ε_ij に一般化）。有意差なしペアは重み 0（tie として学習から除外）。
4. **等価性ゲート**(D5/G6): robust equivalence を通過した変種のみ選好対象とし、通過強度（多入力での一致率）を重みに反映。

- **RQ への写像**: RQ1「二値ペア DPO / SFT に対し、リスト構造・実測マージン・不確実性の各注入は正確性と speedup をどれだけ改善するか」（3 部品の ablation が論文の背骨になる）。
- **利点**: 計算コストが DPO と同等（オフライン）。データの素性への忠実さがそのまま新規性になる。SkelDPO との差別化も「表現（skeleton vs diff）」でなく「信号（二値 vs 実測連続量）」の軸に移り、勝ち筋が明確。
- **リスク**: 各部品の効果が小さいと「部品の寄せ集め」に見える。→ ablation を主実験に据え、効果が出る/出ない条件まで含めて報告する設計にする（「適用限界を明らかにする」という背骨と整合）。

### 案 B: 等価性ゲート付き実行接地 RL（挑戦・オンライン）

**核**: D3（安価な実行オラクル）を最大活用し、GRPO で報酬 = 「等価性ゲート ×実測 speedup」を与えるオンライン学習。jsPerf は (i) プロンプト（setup + 遅い実装）の供給源、(ii) 報酬計測基盤、(iii) 人間解による報酬の基準線、として三役で使う。

- **根拠**: Afterburner の「SFT/DPO は飽和、GRPO は継続改善」という知見の JS への移植 + 等価性ゲート（G6）は未踏。GRPO のグループ内相対比較は「同一ベンチ内の複数変種」というデータ構造と同型。correctness ゲート付き speedup 報酬の RL は **SuperCoder**（x86 アセンブリ、テスト全通過時のみ speedup 報酬）が機能実証済みで、テストスイート不在環境での差分テストゲートへの置換が本案の差分になる。
- **利点**: フレームワークとしての物語が最も強い（「マイクロベンチマークは安価な報酬オラクルである」という主張）。reward hacking（JIT トリック、ベンチ過適合）がそのまま §8 Failure Modes の独自知見になる。
- **リスク**: 実装・計算コストが高い。学習中の計測ノイズ制御（pinning 等）が並列化と干渉する。reward hacking の制御に失敗すると主結果が壊れる。

### 案 C: A → B の 2 段階（A で初期化し B で自己改善）

Afterburner の知見に沿った合わせ技。「人間比較知で方策を初期化し、同じ計測基盤で自己改善する」という完結した物語になるが、博士論文級のボリューム。TOSEM 1 本には過剰で、B を小規模比較（サブセットで SFT vs 案 A vs GRPO）に縮めて 7 章の 1 節にするのが現実的。

### 案 D: 変換パターン条件付き生成（SCAM 資産の再利用・従属的）

SCAM の変換パターン抽出を使い、「変換パターンの予測 → 適用」の 2 段生成や rationale 合成 SFT を行う案。ただし空白地帯調査の結果、新規性の核は表現（diff/skeleton）でなく信号（G4/G5）にあるため、**主役には据えず**、案 A の入力表現の ablation（パターン提示あり/なし）として従属的に組み込むのが妥当。

---

## 4. 推奨

**案 A を主役、案 B を縮小版（手法比較実験）として 1 節組み込む構成**を推奨する。

- 貢献の再定義案:
  1. 実測性能とその不確実性を選好信号として扱う学習フレームワーク MG-LPO（G4/G5 を埋める。手法貢献）
  2. jsPerf 由来の等価実装リストデータセットと等価性検証パイプライン（G2/G3/G6。データ貢献 — 主役から降格するが消えない）
  3. JS/V8 における学習挙動の経験的解明（SFT/二値 DPO/MG-LPO/GRPO の比較 + 機構分析 + 世代間可搬性 D4。G1 を埋める）
- RQ 再構成案:
  - RQ1: 実測マージン・リスト構造・不確実性重みの注入は、二値ペア選好学習に対して正確性・speedup をどれだけ改善するか（部品別 ablation）
  - RQ2: 学習パラダイム間比較 — SFT / 二値 DPO / MG-LPO / GRPO（縮小版）はコスト対効果でどう並ぶか
  - RQ3: 学習した最適化知識はどこまで一般化するか（EffiBench-X JS、V8 世代間、入力規模）
- 旧 RQ2（k=n 多様性）は RQ1/RQ3 の評価指標（valid coverage）に吸収する。

## 5. DPO に限定しない手法空間の全体像（2026-07-06 追記）

DPO 固執を外し、チューニング手法全域（選好最適化変種 / 報酬条件付き SFT / 棄却サンプリング自己学習 / トークンレベル信用割当 / 編集ネイティブ生成 / 学習コストモデル / ニューロシンボリック / RLVR 系）を追加調査した結果。手法空間は次の 2 軸で整理できる。

- **軸 1: 実測速度信号の入れ方**（オラクル活用度の階梯）
  1. 条件付き SFT（PIE 型 speedup タグ。ICLR 2024。最安・リスト全体を学習データ化できる）
  2. 棄却サンプリング自己蒸留（RAFT / ReST-EM / BOND。生成 → 実行 → 検証通過のみ再学習。BoN が安価に回る本データと好相性）
  3. オフライン選好最適化（DPO / IPO / KTO / listwise 系: RRHF・BRIO・PRO・LiPO）
  4. オンライン RL（GRPO / RLOO / RLVR。等価性ゲート × ベンチ内相対 speedup 報酬。Afterburner は「SFT/DPO 飽和、GRPO 継続改善」と報告）
  5. 学習された速度クリティック（実行なしで速度ランキングを予測する報酬モデル。TVM のランク学習コストモデルの LLM 版に相当）
- **軸 2: code-to-code 構造への対処**
  - diff による信用割当（正解編集マスク）／恒等アンカー（コピー縮退対策）／編集ネイティブ出力空間（Supersonic 型 diff 出力・LintSeq 型編集列）

### 追加調査で確定した重要ファクト

- **正解 diff マスクをトークン重みに使う選好/RL 損失は未発見**。TIS-DPO・SePO・OTPO・Focused-DPO はいずれもトークン重要度を「推定」しており、編集タスクなら diff アルゴリズムで正解が得られる点を使った研究がない（= 本研究最大の技術的差し込み口）。
- **コピー縮退には理論的裏付けが既にある**: Smaug/DPO-Positive（arXiv 2024、低編集距離ペアで chosen 尤度まで崩壊する失敗モードの解析）と Likelihood Displacement（ICLR 2025、類似ペアでの確率質量流出 + CHES スコア）。「rejected ≒ 入力コピー」という編集タスク固有の縮退の系統解析は未踏。
- **GRPO のグループ相対正規化は「ベンチ内でのみ比較可能」という本データの制約と数学的に同型**。恒等出力は advantage ≈ 0 に自然に落ちる。
- **within-benchmark ペアのみで学習する速度ランキング報酬モデル**（BT/rank RM → リランキング・RL 報酬プロキシ・データフィルタ）を正確にやった先行研究は未発見。
- listwise 選好（BRIO: ACL 2022 / PRO: AAAI 2024 / LiPO / RRHF: NeurIPS 2023）のコード性能への適用例なし。
- 編集ネイティブ出力（Supersonic: TSE 2024 の diff 出力、LintSeq: 編集列 SFT、Coeditor）では、コピー縮退が「空 diff」に写像され選好信号の密度が最大化される。

## 6. 改訂提案: DPO 非依存の 3 貢献構成（2026-07-06 追記）

§3 の案 A–D を包含・再編する。**特定の損失関数（DPO）を貢献にするのではなく、「code-to-code 性能最適化学習の構造的問題への 3 つの原理」を貢献とし、損失ファミリーはその実装として比較する**構成。

### 貢献 1（技術コア）: 編集局在の学習信号（edit-localized learning）

正解 diff マスク（GumTree / Myers）をトークン重みとして損失に注入する。損失非依存の原理であり、(a) listwise 選好（LiPO/BRIO 型 + マスク重み）、(b) GRPO の advantage マスキング、(c) 条件付き SFT の損失マスク、のどれにも適用して効果を比較できる。恒等アンカー（入力自身を speedup=1.0 の疑似変種としてリストに挿入）+ DPOP 型 chosen 尤度保護でコピー縮退を制御。Smaug / Likelihood Displacement を理論的裏付けに使う。

### 貢献 2（経験的解明）: オラクル活用度の階梯比較

軸 1 の階梯（タグ条件付き SFT → RAFT/ReST-EM 自己蒸留 → listwise PO → GRPO）を同一データ・同一評価で比較し、「実行オラクルをどこまで学習に組み込むと何が改善するか」のコスト対効果曲線を描く。Afterburner（SFT vs DPO vs GRPO）の知見を、(i) JS/V8、(ii) 人間実装リスト、(iii) 貢献 1 の部品有無、で拡張する。旧 RQ2 に相当。

### 貢献 3（一般化の媒介）: 方策としての知識 vs 批評家としての知識

ベンチ内ペアのみで Bradley-Terry 速度ランキング RM を学習し（ベンチ間非比較性を構造的に満たす）、(i) k 候補のリランキング、(ii) 実行不能コードへの報酬プロキシ、(iii) EffiBench-X 等への転移で「人間比較知は方策（生成モデル）と批評家（RM）のどちらの形でより良く一般化するか」を問う。RQ3 の一般化分析に科学的な問いの形を与える。

### 実装優先度

1. **主役**: diff マスク重み付き listwise PO + 恒等アンカー（オフライン・7B+LoRA で確実に回る）
2. **対抗・拡張**: 等価性ゲート × tanh(相対 speedup) 報酬の GRPO（縮小版でも階梯比較に必須）
3. **ベースライン**: PIE 型タグ SFT / RAFT 自己蒸留（実装最安・保険を兼ねる）
4. **第 3 貢献**: 速度ランキング RM（学習は軽量。転移実験の主役）
5. **オプション**: Supersonic 型 diff 出力空間の ablation（貢献 1 と直交する第二の表現軸。リスクは 7B の diff 出力の脆さ）

## 7. 主要文献の Zotero 登録（保留中）

2026-07-06 時点で `zotero-cli add` が 403（API キーが書き込み不可）+ ローカル API 接続不可（Zotero アプリ未起動）のため未登録。Zotero デスクトップを起動するか書き込み可能な API キーを設定後、以下で一括登録できる:

```bash
while read -r url; do zotero-cli add url "$url" -c "tuning-survey" --create-collections; done <<'EOF'
https://arxiv.org/abs/2302.07867
https://arxiv.org/abs/2309.14846
https://arxiv.org/abs/2402.01878
https://arxiv.org/abs/2203.16804
https://arxiv.org/abs/2306.17492
https://arxiv.org/abs/2304.05302
https://arxiv.org/abs/2402.03300
https://arxiv.org/abs/2410.04350
https://arxiv.org/abs/2408.13518
https://arxiv.org/abs/2505.18720
https://arxiv.org/abs/2404.11999
https://arxiv.org/abs/2402.13228
https://arxiv.org/abs/2410.08847
https://arxiv.org/abs/2502.11475
https://arxiv.org/abs/2205.13636
https://arxiv.org/abs/2407.14622
https://arxiv.org/abs/2312.06585
https://arxiv.org/abs/2304.06767
https://arxiv.org/abs/2305.14718
https://arxiv.org/abs/2410.02749
https://arxiv.org/abs/2305.18584
https://arxiv.org/abs/2306.17077
https://arxiv.org/abs/2412.17264
https://arxiv.org/abs/2505.23387
https://arxiv.org/abs/2402.07844
https://arxiv.org/abs/2407.14044
https://arxiv.org/abs/2402.01306
https://arxiv.org/abs/2405.14734
https://arxiv.org/abs/2310.12036
https://arxiv.org/abs/2410.10209
https://arxiv.org/abs/2410.05605
https://arxiv.org/abs/2505.13004
EOF
```

内訳: PIE / Supersonic / LiPO / BRIO / PRO / RRHF / GRPO(DeepSeekMath) / TIS-DPO / SePO / OTPO / TDPO / Smaug(DPOP) / Likelihood Displacement / Focused-DPO / Quark / BOND / ReST-EM / RAFT / A-LoL / LintSeq / Coeditor / RAPGen / ACECode / Afterburner / Mercury / ECCO / KTO / SimPO / IPO / EffiCoder / CodeDPO / EffiBench-X。

## 8. 投稿前の要確認事項（調査の検証状態）

- SkelDPO / Afterburner / ACECode / PerfCodeGen / RAPGen / RLEF は arXiv 実在確認済みだが**査読 venue 未確定**（2026-07 時点）。引用時に一次ソース再確認。
- EffiBench-X は arXiv:2505.13004 で **under review 表示**（NeurIPS'25 表記は GitHub のみ）。Kevin は ICML 2025 掲載ページありだが本会議/ワークショップ区分未確定。
- MAGNETO は実在を検証できず — 引用しない。
- SBLLM は TSE ではなく **ICSE 2025**。EffiCoder と SwiftCoder は同一論文の版違い。
- Afterburner / ACECode の報酬が厳密に correctness-gated かは abstract からは断定不可（本文精読が必要）。SuperCoder はゲートを本文で明示確認済み。
