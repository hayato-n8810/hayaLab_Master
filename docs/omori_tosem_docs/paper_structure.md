論文ストーリー草案

# 論文章構成案（TOSEM 向け）

**仮タイトル**:
- A Performance Optimization Learning Method for JavaScript Using a Micebenchmark Service
  - JavaScriptのための，マイクロベンチマークサービスを活用したパフォーマンス最適化学習手法
- 大森修論”マイクロベンチマーク共有サービスを活用した高速化のための自動ファクタリング”
---

## 論文の方向性

人間が性能比較を通じて発見した最適化知識を，マイクロベンチマーク比較履歴から抽出し，意味保存を確認した性能リファクタリング知識として構造化することで，JavaScript/JIT 環境における自動性能改善モデルの構築と，その適用限界を明らかにする．

- データ源の価値は，マイクロベンチマークデータ自体の分析（＋SCAMが通っていれば合わせて）で述べる．
- 主張は「人間比較知は高速化学習の**有効な源泉たりうる**（存在証明）」ぐらい？

---

## Contributions

1. **Human performance optimization knowledge mining**
   人間が作成した microbenchmark 比較から，「ある実装を別の等価実装へ置換することで性能が改善する」という最適化知識を抽出するデータ構築方法を提案する．
   - ※ ただし「データ構築のみ」の論文に見えないよう，貢献 1 は入口とし，貢献 2（学習枠組み）・貢献 3（学習挙動の経験的解明）と**同格**に位置づける．

2. **Semantics-preserving performance refactoring framework**
   動的型付き言語の断片コードに対して，意味・振る舞いの等価性（というかは要検討）を評価しながら性能改善変換を学習する枠組みを提案する．

3. **Empirical characterization of learned optimization behavior**
   V8 runtime measurement を用いて，学習された変換がどの性能機構（allocation reduction, computation reduction, deoptimization avoidance 等）と対応するかを分析し，性能リファクタリング学習の可能性と限界を明らかにする．

---

## 1. Introduction

### 1.1 Background
- 性能改善は重要なソフトウェア保守活動である．
- しかし性能修正は難しい：性能は実行環境依存／動的型付け言語では静的推論が困難／同じ結果を返すコードでも性能特性が異なる．

### 1.2 Problem Statement
既存の自動性能改善研究の不足：
- **Challenge 1: Performance knowledge is implicit** — 開発者は比較実験を通じて高速化方法を発見するが，その知識はコード差分として散在している．
- **Challenge 2: Performance improvement requires semantic preservation** — 高速化だけでは不十分で，振る舞いを保持した変換である必要がある．
- **Challenge 3: JIT environments complicate optimization learning** — JavaScript/V8 では性能が実行時挙動に依存する．

### 1.3 Research Questions
- **RQ1**: 人間比較知から抽出した性能変換知識を学習した提案手法は，**k=1（単一候補生成）**において，既存手法より良い JavaScript 性能リファクタリングを生成できるか．（手法の質．ベースライン比較と差分表現の有無の比較を含む．）
- **RQ2**: **k=n（複数候補生成）**により，どの程度多様な高速化案を生成でき，その多様性は有効な高速化案のカバレッジを高めるか．
- **RQ3**: microbenchmark 由来の性能知識は実規模コード（EffiBench-X-JS）へどこまで一般化するか．**転移の成否でなく，一般化の境界を明らかにする．**

---

## 2. Related Work

### 2.1 Performance Bug Detection and Repair
- 対象：performance bug fixing / optimization recommendation / refactoring recommendation．
- 位置づけ：既存研究は「既知の性能問題を修正する」．本研究は「人間が探索した性能改善知識を抽出する」．

### 2.2 Mining Software Engineering Knowledge
- 関連：commit mining / code change mining / transformation mining．
- 差分：既存はバグ修正・保守変更．本研究は性能比較から得られる optimization knowledge．

### 2.3 Automated Program Repair and Refactoring
- 関連：semantics preservation / automated transformation．
- 本研究との差：性能目的の変換を扱う．

### 2.4 Efficiency-Oriented Code Generation and Preference Learning
- SFT / DPO / code generation preference learning の概観．DPO は学習**手段**であり，研究対象は性能知識抽出であると位置づける．
- 効率志向コード生成の最前線：PIE / Supersonic（slow→fast 編集，C/C++・静的に正解が決まる世界），EffiCoder（効率コードへの SFT），CodeDPO（効率選好 DPO），SkelDPO（効率実装の**共通**skeleton を選好，Python/競プロ），効率ベンチ（Mercury / ENAMEL / EffiBench / EffiBench-X）．
- **差分を示す（列：データ源／言語／タスク（生成 or リファクタリング）／意味保存検証の有無など）**．本研究は (i) 人間比較知，(ii) JS/V8，(iii) 断片の意味保存検証，(iv) 変更差分に注目する？（SkelDPO は対抗馬ではなく対比）．

---

## 3. Human Performance Optimization Knowledge

> 本研究の中心章．**データ源の価値を「比較実験」でなく「記述的特徴づけ」で支える要の章．** 機構ラベル（動的計装）が登場する一方の端．

### 3.1 Concept of Performance Comparison Knowledge
- microbenchmark 比較は slow implementation ＋ fast implementation という形で「性能改善変換」を明示的に含む．

### 3.2 Why Human Comparisons?
- LLM 生成コード／競プロ解／human benchmark comparison の対比．
- human comparison の特徴：実測された性能差／意図的な比較／最適化探索過程の痕跡．
- ※ ここは**定性的な対比**程度．定量的な優劣主張はおそらくできない．

### 3.3 Empirical Analysis（データ源価値の記述的特徴づけ）
- 収集データの説明． 速度差の分布・具体的なサンプル・その振る舞い を示し，学習する価値があること（差が偶発でなく構造的にあること）を示す．
- **V8 計測（allocation / GC / deoptimization / retired instruction）による説明をする** — このデータの高速化が「割当削減／計算量削減／API 差し替え型」など，どのようなプログラムの比較をどの比率で含むかを定量化．
- 目的：「人間比較知には実測裏付きで多様な機構の高速化が含まれる」ことを記述的に示し，データ源としての価値を支える（SCAMが通っていれば引用）
- コンパイラのバージョンに依る可能性があるので学習には用いない方向で．考察に使うぐらい

---

## 4. Dataset Construction

> 柱(2) 意味・振る舞いの等価性（というかは要検討）の本体．

### 4.1 Collecting Microbenchmark Comparisons
- 対象：JsPerf 等．処理：最新 revision 採用／極端なコード（文字数上位）除外／重複除去（大森論文準拠）

### 4.2 Performance Measurement
- 測定条件：warmup（JIT 階層到達のため回数の感度確認）／CPU isolation（コア pinning）／frequency control／confidence interval（95% 信頼区間で統計的に速い/遅いを判定）．
- データセット中のプログラムをいじらない方向で
- setupとtestを結合して計測 or 結合せず計測（要検討）

### 4.3 Semantic Preservation Verification
- 中心課題：性能改善 ≠ 正しい変換．
- 方法：標準出力・終了時変数値（toString・valueOf）・式評価の比較を母体に多入力化（大森論文準拠）
- 分類：**single-input equivalence** と **robust equivalence** を区別．

### 4.4 Knowledge Representation
- 抽象化（未使用変数除去，変数/関数の正規化，リテラル保持）
- 差分取得（？）

---

## 5. Learning Framework

### 5.1 Overview
- 目的：実行速度向上のリファクタリングタスクに向けたLLMの学習
- 構成：SFT（ファインチューニング）・Preference optimization / モデルを変えて比較？

### 5.2 Code-level Preference Learning
- slow = rejected，fast = chosen の DPO．同一の遅いコードに対し効率的な等価実装を選好させる．

### 5.3 Transformation-aware Preference
- 差分表現：抽象化後の slow→fast を並列解析し，変更された部分（低速にのみ／高速にのみ現れる要素）を抽出してDPOの指標（skeleton?）とする．
- 目的：「どの変更が性能改善候補として現れるか」を学習する．
- **※ skeleton（差分表現）自体は研究貢献ではなく表現方法**．共通構造でなく差分で作る理由＝microbench はそもそも比較のためにペアで作られた比較知であり，共通部分より差分を取る方がデータの素性に忠実，という**設計判断**として述べる（共通構造版との比較実験は行わないというより行えない）．
- 変更差分と効率性の関係は考察程度？

### 5.4 Objective
- Combined objective：code preference loss ＋ transformation preference loss（モデルの結合）
- 準拠：SkelDPO- A Skeleton-Guided Direct Preference Optimization Framework for Efficient Code Generation

---

## 6. Experimental Setup

### 6.1 Models
- base model（post-train なし）／SFT のみ／code preference optimization のみ（差分表現なし）／proposed．
- qwenとか？複数サイズ（小型〜7B 級） CodeT5+ を利用するかは要検討，

### 6.2 Baselines
- 比較軸：素モデル / SFT / 差分表現なしの code-DPO / GPTとかClaude? / 差分をSkeletonとしたDPO（提案？） 
- ※ データ源差し替え（LLM 生成ペア）はコスト的に可能であれば．基本は行わない方向

### 6.3 Evaluation Metrics
- **Correctness**：robust equivalence rate（頑健等価で分けた成功率）4章の手法で処理結果を比較
- **Performance（RQ1, k=1）**：正確性＋実行時間向上幅とその統計
- **Search/Diversity（RQ2, k=n）**：unique valid optimization（有効案カバレッジ＝n 案中少なくとも 1 つが等価かつ高速な率），transformation coverage，および候補間の **AST 距離・編集距離・API/メソッド種別の散らばり**（出力の多様性とかを計測するイメージ）
- 統計と公平性：best-of-k を全モデルで対称化，複数 seed の分散・信頼区間，モデル間差の有意性検定．
- データ分割：ペア単位でなく**ベンチ単位（可能なら機能クラスタ単位）**でリーク排除．

### 6.4 Generalization Benchmark
- 対象：EffiBench-X-JS（JS対応のLLMコード生成ベンチマーク）
- 目的：一般化可能性の検証
- 準備：非効率な生成 JS コードを入力とする**リファクタリングタスクに変換**し，テストスイートで正当性検証，ET/MI で効率測定．最小構成（一部タスク・主力モデル）．

---

## 7. Results

### 7.1 RQ1（k=1 の質）
- 問い：マイクロベンチマークサービスを学習した提案手法は，k=1 で既存手法より良い性能リファクタリングを生成できるか．
- 評価：correctness（robust equivalence rate）と performance（speedup・%optimized）．
- ベースライン比較（素モデル / SFT のみ / code-DPO のみ）に加え，**差分表現の有無**および**クレンジング有無**の比較をここに含め，提案手法の核とデータ精錬の寄与を担保．重み感度はここでの手法分析として併記．

### 7.2 RQ2（k=n の多様性とカバレッジ）
- 問い：複数候補生成は多様で有効な高速化探索を可能にするか．
- 分析：candidate diversity（AST 距離・編集距離・API 種別の散らばり）と valid optimization coverage（少なくとも 1 案が頑健等価かつ高速な率）．「多様に出すことが当たりを増やすか」を示す．

### 7.3 RQ3（汎化の境界）
- 問い：転移はどこで成功し，どこで失敗するか．
- 分析：microbenchmark（small local transformations）と ベンチマークにおける実利用（？）（larger context dependency）の対比．改善率や再利用可能な知識なども評価

---

## 8. Discussion

### 8.1 What Optimization Knowledge Does the Model Learn?
- V8 analysis：生成された改善が allocation reduction / computation reduction / JIT optimization のどれに対応するか．RQ2 で示した構造・API の多様性を，機構の側からここで初めて結びつける．

### 8.2 Failure Modes
- benchmark overfitting／invalid optimization／runtime-specific tricks．多入力検証で落ちた変換（限定的 XOR，eval 利用 等）の比率と類型を，頑健な機構由来の高速化と対比．「ベンチマーク由来データで学ぶことの固有リスク」を独自知見として体系化．

### 8.3 Input Scale and Refactoring Performance
- 入力トークン長などに対する修正成功率の傾向．RQ1/RQ2 を入力長で層別した補足分析，および RQ3（より大きい入力への転移）と接続して論じる．

### 8.4 Implications for Software Engineering
- マイクロベンチマークおよびそのサービスは自動リファクタリングモデルの学習の有効なデータとなり得るかどうか
- クローズドモデルとか，LLMの出力を高めるのではなく絶対的に速いコードが候補として上がるといいよねみたいな

---

## 9. Threats to Validity

### 9.1 Construct validity（本研究の急所・厚く論じる）
- 多入力でも漏れる等価判定の問題／計測ノイズ（warmup・pinning）／効率指標が「測りたいものを測れているか」

### 9.2 Internal validity
- data leakage（ベンチ単位分割で対処）／preprocessing bias（抽象化・長いプログラム除外）／差分表現のノイズ．

### 9.3 External validity
- V8 dependency（バージョン依存）／microbenchmark vs production code の乖離／学習データの質と EffiBench-X の V8 世代差．

### 9.4 Reproducibility（TOSEM 向けに追加）
- データ・コードの公開，測定環境（Node/V8 バージョン，CPU，pinning，flags）の完全記述．

---

## 10. Conclusion

- 本研究は，性能比較を通じて蓄積された人間の最適化知識を抽出し，意味保存型 JavaScript 性能リファクタリングへ利用する方法を示した．
- **どこまでできて，どこからできないか**を正面から述べる（背骨の「適用限界を明らかにする」と一貫）：人間比較知は有効な源泉たりうるが，その効果は V8 環境・断片規模・頑健等価の成否に条件づけられる．
- 今後：OSS 実コードへの適用／他言語展開／maintainability との同時最適化．
