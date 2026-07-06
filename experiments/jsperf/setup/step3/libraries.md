# Step3 試行ライブラリ一覧

`outputs/jsperf/setup/step1/cdn_list.json`（4,168 URL）の解析結果に基づく試行対象。

## 分類サマリ

| Tier | 分類 | ライブラリ数 | 元 URL カバー数 | 期待動作 |
|---|---|---|---|---|
| A | npm 解決 (node_ok) | 26 | 328 | Node 実行成功 |
| B | uncertain (Node OK 候補) | 12 | ~24 | Node 実行成功が多いはず |
| C | Playwright tier (DOM 依存) | 32 | 654+ | Node で失敗 → Playwright 送り確認 |

## Tier A: npm 解決リスト（node_ok, 26 libraries）

DOM 非依存の純粋 JS ライブラリ。 URL 数の多い順。

| npm パッケージ | URL 数 | バージョン | バインド名 | url-pattern |
|---|---|---|---|---|
| lodash | 113 | ^4.17.21 | `_` | `lodash` |
| underscore | 54 | ^1.13.7 | `_` | `underscore` |
| handlebars | 33 | ^4.7.8 | `Handlebars` | `handlebars` |
| moment | 18 | ^2.30.1 | `moment` | `moment` |
| immutable | 14 | ^4.3.7 | `Immutable` | `immutable` |
| mustache | 13 | ^4.2.0 | `Mustache` | `mustache` |
| ramda | 11 | ^0.30.1 | `R` | `ramda` |
| bluebird | 11 | ^3.7.2 | `Promise` | `bluebird` |
| hogan.js | 7 | ^3.0.2 | `Hogan` | `hogan` |
| sugar | 7 | ^2.0.6 | `Sugar` | `sugar` |
| crypto-js | 7 | ^4.2.0 | `CryptoJS` | `crypto` |
| async | 6 | ^3.2.6 | `async` | `async` |
| q | 6 | ^1.5.1 | `Q` | `q.js` |
| mathjs | 5 | ^13.2.3 | `math` | `mathjs` |
| rxjs | 4 | ^7.8.1 | `rxjs` | `rxjs` |
| coffeescript | 3 | ^2.7.0 | `CoffeeScript` | `coffee` |
| linq | 3 | ^4.0.3 | `Enumerable` | `linq` |
| seedrandom | 2 | ^3.0.5 | `seedrandom` | `seedrandom` |
| big.js | 2 | ^6.2.2 | `Big` | `big.js` |
| bignumber.js | 2 | ^9.1.2 | `BigNumber` | `bignumber` |
| chance | 2 | ^1.1.12 | `Chance` | `chance` |
| decimal.js | 1 | ^10.4.3 | `Decimal` | `decimal` |
| marked | 1 | ^14.1.3 | `marked` | `marked` |
| showdown | 1 | ^2.1.0 | `showdown` | `showdown` |
| es5-shim | 1 | ^4.6.7 | `_es5shim` | `es5-shim` |
| es6-shim | 1 | ^0.35.8 | `_es6shim` | `es6-shim` |

## Tier B: uncertain クラスから Node OK と判定した候補（12 libraries）

`analyze_cdn_v2.py` の uncertain クラスから、パッケージ性質を人手判定して Node で動く可能性が高いもの。

| npm パッケージ | URL 数 | バージョン | バインド名 | url-pattern |
|---|---|---|---|---|
| underscore.string | 3 | ^3.3.6 | `s` | `underscore.string` |
| gl-matrix | 3 | ^3.4.3 | `glMatrix` | `gl-matrix` |
| markdown-it | 2 | ^14.1.0 | `MarkdownIt` | `markdown-it` |
| remarkable | 2 | ^2.0.1 | `Remarkable` | `remarkable` |
| crossfilter2 | 2 | ^1.5.4 | `crossfilter` | `crossfilter` |
| mori | 2 | ^0.3.2 | `mori` | `mori` |
| dayjs | 2 | ^1.11.13 | `dayjs` | `dayjs` |
| @babel/core | 2 | ^7.25.9 | `babel` | `babel` |
| pug | 2 | ^3.0.3 | `pug` | `jade` |
| hash-wasm | 2 | ^4.11.0 | `hashwasm` | `hash-wasm` |
| dustjs-linkedin | 3 | ^3.0.1 | `dust` | `dust` |
| json3 | 3 | ^3.3.3 | `JSON3` | `json3` |

## Tier C: Playwright tier 送り確認用（32 libraries）

DOM/描画依存で Node 実行不可が予測されるが、実測で確認する。

| npm パッケージ | 想定 URL 数 | バージョン | バインド名 | url-pattern |
|---|---|---|---|---|
| jquery | 200+ | ^3.7.1 | `$` | `jquery-` |
| jquery-ui | 12+ | ^1.13.3 | `_jqueryui` | `jquery/ui` |
| jquery-mobile | 7 | ^1.5.0 | `_jqm` | `jquery-mobile` |
| jquery-color | 数個 | ^2.2.0 | `_jqcolor` | `jquery.color` |
| angular | 113 | ^1.8.3 | `angular` | `angular` |
| backbone | 22 | ^1.6.0 | `Backbone` | `backbone` |
| react | 22 | ^18.3.1 | `React` | `react` |
| react-dom | 数個 | ^18.3.1 | `ReactDOM` | `react-dom` |
| knockout | 19 | ^3.5.1 | `ko` | `knockout` |
| vue | 6 | ^3.5.13 | `Vue` | `vue` |
| ember-source | 8 | ^5.12.0 | `Ember` | `ember` |
| mithril | 13 | ^2.2.13 | `m` | `mithril` |
| mootools-core | 17 | ^1.6.0 | `MooTools` | `mootools` |
| prototype | 9 | ^1.7.3 | `Prototype` | `prototype` |
| dojo | 33 | ^1.18.0 | `dojo` | `dojo` |
| zepto | 7 | ^1.2.0 | `_zepto` | `zepto` |
| d3 | 9 | ^7.9.0 | `d3` | `d3` |
| raphael | 4 | ^2.3.0 | `Raphael` | `raphael` |
| paper | 4 | ^0.12.18 | `paper` | `paper.js` |
| three | 数個 | ^0.169.0 | `THREE` | `three` |
| pixi.js | 数個 | ^8.5.2 | `PIXI` | `pixi` |
| highcharts | 数個 | ^11.4.8 | `Highcharts` | `highcharts` |
| leaflet | 数個 | ^1.9.4 | `L` | `leaflet` |
| chart.js | 数個 | ^4.4.5 | `Chart` | `chart` |
| gsap | 12 | ^3.13.0 | `gsap` | `gsap` |
| hammerjs | 数個 | ^2.0.8 | `Hammer` | `hammer` |
| bootstrap | 2+ | ^5.3.3 | `_bootstrap` | `bootstrap` |
| select2 | 数個 | ^4.0.13 | `_select2` | `select2` |
| p5 | 数個 | ^1.11.2 | `p5` | `p5` |
| howler | 数個 | ^2.2.4 | `Howler` | `howler` |
| tone | 数個 | ^15.0.4 | `Tone` | `tone` |

## 実行順

推奨は A → B → C の順:

```bash
# コンテナ内 /workspace で
bash experiments/jsperf/setup/step3/run_tier_a_node_ok.sh
bash experiments/jsperf/setup/step3/run_tier_b_uncertain.sh
bash experiments/jsperf/setup/step3/run_tier_c_playwright.sh
```

各 tier の結果は `outputs/jsperf/setup/step3/trials/<library>/summary.json` に集計される。

## 注意

### URL パターンの重複
`--url-pattern` は case-insensitive 部分一致。以下のような重複が起きる:

- `--url-pattern jquery-` は `jquery-ui-*` や `jquery-mobile-*` URL にもマッチ
- `--url-pattern underscore` は `underscore.string` URL にもマッチ
- `--url-pattern angular` は `angular-filter` などにもマッチ

各 trial は「該当ライブラリの require のみ」を挿入するので、他ライブラリも必要な program はその trial では失敗する。 これは仕様通り: 単一ライブラリの効果を独立に測るのが本 step の目的。

### 出力ディレクトリ
`outputs/jsperf/setup/step3/trials/<library>/`
- `results.jsonl`
- `summary.json`
- `<slug_id>/program_<i>.js`

同名ライブラリで再試行すると上書きされる（意図通り）。

### バインド名の衝突
既存 program の変数名と `--binding` が衝突する可能性はゼロではないが、実際の jsperf コードでは短い記号（`_`, `$`, `R`, `Q` 等）以外は稀。 発生した場合は `TypeError` として記録される。
