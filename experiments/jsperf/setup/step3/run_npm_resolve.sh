#!/usr/bin/env bash
# Tier A: npm 解決リスト (node_ok, 26 libraries, 328 元 URL カバー)
# DOM 非依存の純粋 JS ライブラリ群。 Node 実行成功が期待される。
#
# 実行方法 (Docker step3 コンテナ内、/workspace で):
#   bash experiments/jsperf/setup/step3/run_tier_a_node_ok.sh
#
# 個別実行したい場合はこのファイルの該当行をコピー実行。
# エラーが出ても後続を継続する (`set -e` を付けない)。

CMD="uv run python experiments/jsperf/setup/step3/trial_library.py"

# --- URL 数の多い順 ---
$CMD --library lodash        --version "^4.17.21" --binding _            --url-pattern lodash
$CMD --library underscore    --version "^1.13.7"  --binding _            --url-pattern underscore
$CMD --library handlebars    --version "^4.7.8"   --binding Handlebars   --url-pattern handlebars
$CMD --library moment        --version "^2.30.1"  --binding moment       --url-pattern moment
$CMD --library immutable     --version "^4.3.7"   --binding Immutable    --url-pattern immutable
$CMD --library mustache      --version "^4.2.0"   --binding Mustache     --url-pattern mustache
$CMD --library ramda         --version "^0.30.1"  --binding R            --url-pattern ramda
$CMD --library bluebird      --version "^3.7.2"   --binding Promise      --url-pattern bluebird
$CMD --library hogan.js      --version "^3.0.2"   --binding Hogan        --url-pattern hogan
$CMD --library sugar         --version "^2.0.6"   --binding Sugar        --url-pattern sugar
$CMD --library crypto-js     --version "^4.2.0"   --binding CryptoJS     --url-pattern crypto
$CMD --library async         --version "^3.2.6"   --binding async        --url-pattern async
$CMD --library q             --version "^1.5.1"   --binding Q            --url-pattern q.js
$CMD --library mathjs        --version "^13.2.3"  --binding math         --url-pattern mathjs
$CMD --library rxjs          --version "^7.8.1"   --binding rxjs         --url-pattern rxjs
$CMD --library coffeescript  --version "^2.7.0"   --binding CoffeeScript --url-pattern coffee
$CMD --library linq          --version "^4.0.3"   --binding Enumerable   --url-pattern linq
$CMD --library seedrandom    --version "^3.0.5"   --binding seedrandom   --url-pattern seedrandom
$CMD --library big.js        --version "^6.2.2"   --binding Big          --url-pattern big.js
$CMD --library bignumber.js  --version "^9.1.2"   --binding BigNumber    --url-pattern bignumber
$CMD --library chance        --version "^1.1.12"  --binding Chance       --url-pattern chance
$CMD --library decimal.js    --version "^10.4.3"  --binding Decimal      --url-pattern decimal
$CMD --library marked        --version "^14.1.3"  --binding marked       --url-pattern marked
$CMD --library showdown      --version "^2.1.0"   --binding showdown     --url-pattern showdown
$CMD --library es5-shim      --version "^4.6.7"   --binding _es5shim     --url-pattern es5-shim
$CMD --library es6-shim      --version "^0.35.8"  --binding _es6shim     --url-pattern es6-shim

echo "=== tier A finished ==="


# Tier B: uncertain クラスから Node OK と判定したもの (12 libraries)
# 純粋 JS の可能性が高いが、実測で確認したい候補群。

# --- 純粋 JS 可能性が高い候補 ---
$CMD --library underscore.string --version "^3.3.6"   --binding s            --url-pattern underscore.string
$CMD --library gl-matrix         --version "^3.4.3"   --binding glMatrix     --url-pattern gl-matrix
$CMD --library markdown-it       --version "^14.1.0"  --binding MarkdownIt   --url-pattern markdown-it
$CMD --library remarkable        --version "^2.0.1"   --binding Remarkable   --url-pattern remarkable
$CMD --library crossfilter2      --version "^1.5.4"   --binding crossfilter  --url-pattern crossfilter
$CMD --library mori              --version "^0.3.2"   --binding mori         --url-pattern mori
$CMD --library dayjs             --version "^1.11.13" --binding dayjs        --url-pattern dayjs
$CMD --library "@babel/core"     --version "^7.25.9"  --binding babel        --url-pattern babel
$CMD --library pug               --version "^3.0.3"   --binding pug          --url-pattern jade
$CMD --library hash-wasm         --version "^4.11.0"  --binding hashwasm     --url-pattern hash-wasm
$CMD --library dustjs-linkedin   --version "^3.0.1"   --binding dust         --url-pattern dust
$CMD --library json3             --version "^3.3.3"   --binding JSON3        --url-pattern json3

echo "=== tier B finished ==="

# Tier C: DOM/描画依存ライブラリ (32 libraries, 654 元 URL)
# Node で require() すると document/window 等の未定義参照で失敗することが期待される。
# 実測で失敗を確認して Playwright tier 送りの根拠として記録する。

# --- jQuery ファミリー (最多、301+ URL) ---
$CMD --library jquery         --version "^3.7.1"    --binding "\$"        --url-pattern jquery-
$CMD --library jquery-ui      --version "^1.13.3"   --binding _jqueryui   --url-pattern "jquery/ui"
$CMD --library jquery-mobile  --version "^1.5.0"    --binding _jqm        --url-pattern jquery-mobile
$CMD --library jquery-color   --version "^2.2.0"    --binding _jqcolor    --url-pattern "jquery.color"

# --- AngularJS 系 ---
$CMD --library angular        --version "^1.8.3"    --binding angular     --url-pattern angular

# --- SPA フレームワーク ---
$CMD --library backbone       --version "^1.6.0"    --binding Backbone    --url-pattern backbone
$CMD --library react          --version "^18.3.1"   --binding React       --url-pattern react
$CMD --library react-dom      --version "^18.3.1"   --binding ReactDOM    --url-pattern react-dom
$CMD --library knockout       --version "^3.5.1"    --binding ko          --url-pattern knockout
$CMD --library vue            --version "^3.5.13"   --binding Vue         --url-pattern vue
$CMD --library ember-source   --version "^5.12.0"   --binding Ember       --url-pattern ember
$CMD --library mithril        --version "^2.2.13"   --binding m           --url-pattern mithril

# --- レガシー DOM フレームワーク ---
$CMD --library mootools-core  --version "^1.6.0"    --binding MooTools    --url-pattern mootools
$CMD --library prototype      --version "^1.7.3"    --binding Prototype   --url-pattern prototype
$CMD --library dojo           --version "^1.18.0"   --binding dojo        --url-pattern dojo
$CMD --library zepto          --version "^1.2.0"    --binding _zepto      --url-pattern zepto

# --- 可視化 / 描画 ---
$CMD --library d3             --version "^7.9.0"    --binding d3          --url-pattern d3
$CMD --library raphael        --version "^2.3.0"    --binding Raphael     --url-pattern raphael
$CMD --library paper          --version "^0.12.18"  --binding paper       --url-pattern paper.js
$CMD --library three          --version "^0.169.0"  --binding THREE       --url-pattern three
$CMD --library pixi.js        --version "^8.5.2"    --binding PIXI        --url-pattern pixi
$CMD --library highcharts     --version "^11.4.8"   --binding Highcharts  --url-pattern highcharts
$CMD --library leaflet        --version "^1.9.4"    --binding L           --url-pattern leaflet
$CMD --library chart.js       --version "^4.4.5"    --binding Chart       --url-pattern chart

# --- アニメーション / インタラクション ---
$CMD --library gsap           --version "^3.13.0"   --binding gsap        --url-pattern gsap
$CMD --library hammerjs       --version "^2.0.8"    --binding Hammer      --url-pattern hammer

# --- UI ライブラリ ---
$CMD --library bootstrap      --version "^5.3.3"    --binding _bootstrap  --url-pattern bootstrap
$CMD --library select2        --version "^4.0.13"   --binding _select2    --url-pattern select2

# --- メディア / インタラクティブ ---
$CMD --library p5             --version "^1.11.2"   --binding p5          --url-pattern p5
$CMD --library howler         --version "^2.2.4"    --binding Howler      --url-pattern howler
$CMD --library tone           --version "^15.0.4"   --binding Tone        --url-pattern tone

echo "=== tier C finished ==="

# --- 集計 ---
uv run python experiments/jsperf/setup/step3/aggregate_trials.py