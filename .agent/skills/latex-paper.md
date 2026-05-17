---
name: latex-paper
description: |
  LaTeXで学術論文・研究レポートを執筆・編集するためのスキル。
  次のような場面で必ず使用すること：
  - 「論文を書いて」「LaTeXで書いて」「.texファイルを作成して」と言われたとき
  - 既存の .tex ファイルの編集・章追加・修正を依頼されたとき
  - BibTeX参考文献の管理、図・表・数式の挿入を頼まれたとき
  - latexmk や pdflatex でのコンパイルを行うとき
  - 「アブスト書いて」「関連研究を書いて」など論文の一部を書くよう言われたとき
  ユーザーが明示的にスキルを求めなくても、論文・レポート・学術文書の文脈であれば積極的に使用すること。
---

# LaTeX 論文執筆スキル

Claude Codeで `.tex` ファイルに学術論文を書くための手順と規則をまとめたスキル。

---

## 0. 作業開始前の確認事項

作業を始める前に、以下をユーザーに確認または推定する：

| 項目 | 確認内容 | デフォルト |
|------|----------|-----------|
| フォーマット | IEEE / ACM / jsarticle / 汎用 | 汎用 (article) |
| 言語 | 日本語 / 英語 / 両方 | ユーザーの指示言語に合わせる |
| コンパイラ | pdflatex / lualatex / platex | pdflatex（日本語ならlualatex） |
| 参考文献 | BibTeX / biber / なし | BibTeX |
| 環境 | ローカルTeX / Docker | ローカル優先 |

既にプロジェクトに `.tex` ファイルがある場合は、まず内容を読んでからスタイルを把握する。

---

## 1. フォーマット別テンプレート選択

詳細テンプレートは `references/templates.md` を参照。ここでは選択指針のみ示す。

```
ユーザー指定フォーマット
├── IEEE → \documentclass[conference]{IEEEtran}  (references/templates.md § IEEE)
├── ACM  → \documentclass[sigconf]{acmart}        (references/templates.md § ACM)
├── 日本語学術 → \documentclass[12pt]{jsarticle}  (references/templates.md § jsarticle)
└── 汎用/未指定 → \documentclass[12pt]{article}   (references/templates.md § Generic)
```

**重要**: ユーザーが投稿先を言及したらその学会の公式テンプレートに従う。

---

## 2. プロジェクト構成

論文プロジェクトは以下の構成を標準とする：

```
paper/
├── main.tex            # メインファイル（文章はこのファイルのみで完結させる）
├── figures/            # PDF/PNG/EPS 図ファイル
├── tables/             # 複雑な表は別ファイルに
├── bib/                # ★ 参考文献として利用する論文PDF群
│   ├── smith2023.pdf
│   ├── jones2022.pdf
│   └── ...             # 引用候補論文を自由に置く
├── point/              # ★ 執筆指針・原案ファイル群
│   ├── original.pdf    # 原案・たたき台となる論文
│   ├── structure.md    # 章構成・アウトライン
│   ├── notes.md        # 注意点・査読コメントなど
│   └── ...             # PDF / MD どちらでも可
├── references.bib      # BibTeX エントリ（bib/PDFから生成）
└── .latexmkrc          # latexmk 設定
```

---

## 3. 執筆ワークフロー

### Step 0: `point/` と `bib/` の読み込み（★ 必須の最初のステップ）

作業開始時に必ず以下の順で読み込む

```
point/ → bib/ の順で読む
```

**point/ の読み込み**（執筆方針の確定）:

- 章構成・アウトラインが書かれた`structure.md`ファイルを最優先で読む
- 「注意点」「査読コメント」「スタイル指示」があればすべて把握する
- 原案論文がある場合は構成・論点・用語を把握する

**bib/ の読み込み**（参考文献の把握）:

- あくまで参考文献の候補であり，関連がないなら無視すること
- 各論文の「何を主張しているか」「どの手法か」を把握
- `references.bib` に未登録の論文は BibTeX エントリを追加する
- Related Work で引用する論文をリストアップしておく

### Step 1: 骨格の作成
1. `point/` の章構成指示に従って `main.tex` のプリアンブルを作成
2. 章構成（`\section`）を先に配置する


### Step 2: コンテンツの執筆
各セクションをユーザーの指示と `point/` の方針に従って執筆。執筆順の推奨：
```
Method → Experiments → Introduction → Related Work → Abstract → Conclusion
```
- 不確定な要素や，検証の必要がある要素，文章として確認が必要な箇所は`\todo`コマンドで示すこと．
- `bib/` の論文を適宜参照しながら Related Work・Introduction を執筆
- `point/` の注意点を常に念頭に置く（スタイル・用語・主張の一貫性）
- 不確定な情報がある場合は`\todo`コマンドで"参考文献を確認する"というコメントを残すこと
- `bib/`および`point/original.pdf`で参照している論文であったとしても，`\todo`コマンドで"参考文献を確認する"というコメントを残す

### Step 3: 図・表・数式の挿入
優先順位を
```
PDF > EPS > PNG > JPG
```
とし，`figure/`を参照すること．図が存在しないが参照が必要そうな場合は`\todo`コメントで明示すること．

### Step 4: 参考文献の管理
`bib/` や `point\` の PDF から抽出した情報をもとに `references.bib` を整備する。

### .bib ファイルの構造
```bibtex
% references.bib

@article{lecun1989backprop,
  author    = {LeCun, Yann and Boser, Bernhard and Denker, John S and Henderson, Donnie and Howard, Richard E and Hubbard, Wayne and Jackel, Lawrence D},
  title     = {Backpropagation Applied to Handwritten Zip Code Recognition},
  journal   = {Neural Computation},
  year      = {1989},
  volume    = {1},
  number    = {4},
  pages     = {541--551},
  doi       = {10.1162/neco.1989.1.4.541},
}

@inproceedings{vaswani2017attention,
  author    = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob and Jones, Llion and Gomez, Aidan N and Kaiser, {\L}ukasz and Polosukhin, Illia},
  title     = {Attention Is All You Need},
  booktitle = {Advances in Neural Information Processing Systems},
  year      = {2017},
  volume    = {30},
}

@book{goodfellow2016deeplearning,
  author    = {Goodfellow, Ian and Bengio, Yoshua and Courville, Aaron},
  title     = {Deep Learning},
  publisher = {MIT Press},
  year      = {2016},
  url       = {http://www.deeplearningbook.org},
}

@misc{brown2020gpt3,
  author        = {Brown, Tom B and others},
  title         = {Language Models are Few-Shot Learners},
  year          = {2020},
  eprint        = {2005.14165},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
}
```

### BibTeX キー命名規則
```
{著者名(小文字)}{年}{キーワード}
例: lecun1989backprop, vaswani2017attention, brown2020gpt3
```

---

## エントリタイプ別フィールド

### @article（査読付き論文誌）
必須: `author, title, journal, year`
推奨: `volume, number, pages, doi`

### @inproceedings（学会論文）
必須: `author, title, booktitle, year`
推奨: `pages, publisher, address`
IEEEなら: `organization` も使う

### @book（書籍）
必須: `author, title, publisher, year`
推奨: `edition, isbn`

### @misc（arXiv・技術レポート等）
必須: `author, title, year`
推奨: `eprint, archivePrefix, primaryClass, url`

### @phdthesis / @mastersthesis（学位論文）
必須: `author, title, school, year`

---

## 引用コマンド

```latex
% 標準
\cite{vaswani2017attention}         % [1] または [Vaswani et al., 2017]

% IEEE の場合（cite パッケージ）
\usepackage{cite}
\cite{ref1, ref2, ref3}             % [1]–[3] と自動圧縮
```

---

## 参考文献スタイル（\bibliographystyle）

| スタイル | 用途 |
|---------|------|
| `plain` | 番号順、全フィールド表示 |
| `unsrt` | 引用順 |
| `alpha` | 著者名略称+年（[Va17]形式） |
| `IEEEtran` | IEEE学会向け |
| `ACM-Reference-Format` | ACM学会向け |
| `apalike` | APA形式（natbibと組み合わせ）|
| `junsrt` | 日本語対応、引用順 |
| `jplain` | 日本語対応、著者名順 |

---

## Google Scholar からの .bib 取得手順

1. 論文を検索
2. 引用マーク（❝）をクリック
3. "BibTeX" を選択
4. テキストをコピーして `references.bib` に貼り付け
5. キー名を命名規則に合わせて編集

**arXiv の場合**: Abstract ページ → "Export BibTeX Citation" リンク

## よくある問題

### 文字化け（著者名のアクセント等）
```bibtex
% 正しい表記
author = {M{\"u}ller, Hans and {\'E}va N{\'e}meth and {\L}ukasz Kaiser},
```

### URLが長くて表示が崩れる
```latex
\usepackage{url}
% または hyperref の breaklinks オプション
\usepackage[breaklinks]{hyperref}
```

### Step 5: コンパイルと確認
論文執筆後，コンパイルを実施し，
- コンパイルエラーが発生していないかを確認すること．
- `\build`に`main.pdf`が作成されることを確認すること．

---

## 4. 執筆品質ルール

### 文章スタイル
- **英語論文**: 受動態より能動態を優先（"We propose..." > "A method is proposed..."）
  - ただし IEEE/ACM では "This paper presents..." も一般的
- **日本語論文**: 「〜する」「〜である」体で統一
- 一文を短く保つ（英語: 25語以下、日本語: 60文字以下を目安）
- 段落の最初の文でそのパラグラフの主張を述べる（トピックセンテンス）
- "，"および"．"を使用すること．
- 指示語は可能な限り利用しない文構成とすること．

### 数式・記号
```latex
% インライン数式
$x = y + z$

% 番号付き数式（参照する場合）
\begin{equation}
  \label{eq:loss}
  \mathcal{L} = \sum_{i=1}^{N} \ell(y_i, \hat{y}_i)
\end{equation}

% 番号なし数式
\begin{equation*}
  f(x) = \int_0^\infty g(t)\, dt
\end{equation*}

% 複数行
\begin{align}
  a &= b + c \label{eq:first} \\
  d &= e - f \label{eq:second}
\end{align}
```

### 図の挿入
```latex
\begin{figure}[t]  % IEEE: [t]推奨、jsarticle: [htbp]
  \centering
  \includegraphics[width=\linewidth]{figures/result.pdf}
  \caption{実験結果の概要。(a) 提案手法、(b) ベースライン。}
  \label{fig:result}
\end{figure}
```

### 表の挿入
```latex
\begin{table}[t]
  \centering
  \caption{各手法の比較。太字は最良値を示す。}  % IEEE: キャプションは表の上
  \label{tab:comparison}
  \begin{tabular}{lccc}
    \toprule
    Method & Accuracy & F1 & Time (ms) \\
    \midrule
    Baseline & 82.3 & 79.1 & 12.4 \\
    \textbf{Ours} & \textbf{87.6} & \textbf{85.2} & \textbf{11.8} \\
    \bottomrule
  \end{tabular}
\end{table}
```

### 相互参照
```latex
% 常にラベルを使って参照する（ページ番号直書き禁止）
図~\ref{fig:result}に示すように...
式~(\ref{eq:loss})を最小化することで...
表~\ref{tab:comparison}より...
Section~\ref{sec:method}では...
```

---

## 5. コンパイルのクイックリファレンス

環境確認：
```bash
which latexmk && latexmk --version
which pdflatex && pdflatex --version
```

標準的なコンパイル：
```bash
# pdflatex + bibtex
latexmk -pdf main.tex

# 日本語 (lualatex)
latexmk -lualatex main.tex

# 日本語 (platex → dvipdfmx)
latexmk -pdfdvi main.tex
```


---

## 6. よくあるエラーと対処

| エラーメッセージ | 原因 | 対処 |
|-----------------|------|------|
| `Undefined control sequence` | パッケージ未読み込み | プリアンブルに `\usepackage{...}` を追加 |
| `Missing $ inserted` | 数式モード外で数式記号 | `$...$` で囲む |
| `Citation ... undefined` | BibTeX未コンパイル | `bibtex main` 後に再コンパイル |
| `Overfull \hbox` | 行が長すぎる | `\linebreak` や単語を変更 |
| `LaTeX Error: File '...' not found` | 図ファイルが存在しない | パスとファイル名を確認 |
| `! Package babel Error` | 言語設定の競合 | `babel` オプションを確認 |

---
