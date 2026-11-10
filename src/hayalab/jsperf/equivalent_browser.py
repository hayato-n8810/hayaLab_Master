"""ブラウザ (Playwright / Chromium) 上での不等価プログラム除外モジュール.

page_html とプログラムからハーネス HTML を組み立てて 1 回ロードし、console 出力・
プログラム終了時の変数格納値・完了値・DOM を観測して比較する単体処理を提供する。
決定化・変数名収集・計測コード生成は `hayalab.jsperf.equivalent` と共通。
Browser の起動・再起動や結果の保存先は呼び出し側 (`experiments/**`) が決める。
"""

from __future__ import annotations

import hashlib
import json
import time

from hayalab.config.jsperf_config import PLAYWRIGHT_PROGRAM_TIMEOUT_SEC
from hayalab.jsperf.equivalent import (
    STDERR_HEAD_LIMIT,
    STDOUT_HEAD_LIMIT,
    _compare_completion,
    _compare_values,
    _instrument_completion_code,
    _instrument_value_code,
    _variable_names,
    is_completion_comparable,
)

__all__ = [
    "build_page",
    "observe_page",
    "equivalent_output_browser",
    "observe_value_browser",
    "equivalent_value_browser",
    "observe_completion_browser",
    "equivalent_formula_browser",
    "equivalent_dom",
]

# --- 実行パラメータ --------------------------------------------------
TIMEOUT_MS: int = int(PLAYWRIGHT_PROGRAM_TIMEOUT_SEC * 1000)  # ページ 1 回のロード
SCRIPT_LOAD_RETRIES: int = 2  # 外部スクリプトの取得に失敗したときの再試行回数
# fast / slow を同じ URL で読み込み、スタックトレースに現れる URL を一致させる
PAGE_URL: str = "http://hayalab.test/index.html"
# Node で stderr へ出る console メソッド (Playwright の ConsoleMessage.type)。 それ以外は stdout とみなす
STDERR_CONSOLE_TYPES: frozenset[str] = frozenset({"error", "warning", "trace", "assert"})

COLLECT_JS: str = "() => (typeof window.__hl_collect === 'function' ? window.__hl_collect() : null)"


# --- ヘルパ (複数回呼び出し) ----------------------------------------
def _sha256(text: str) -> str:
    """文字列の SHA-256 を返す (孤立サロゲートもそのまま符号化する)."""
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def _hash_record(record: dict | None) -> dict | None:
    """`window.__hl_collect()` が返すハッシュ化前の記録 (`s_sha256` / `v_sha256` に生文字列) をハッシュ化する."""
    if record is None:
        return None
    return {key: _sha256(text) for key, text in record.items()}


def _route_console(msg, stdout_lines: list[str], stderr_lines: list[str]) -> None:
    """ブラウザの console メッセージを Node の stdout / stderr に倣って振り分ける.

    引数を持たないメッセージはブラウザ自身が出したもの (リソース取得失敗・性能警告など) で、
    プログラムの出力ではなく件数もタイミングで揺れるため捨てる。 引数なしの `console.log()` も併せて捨てる。
    """
    if not msg.args:
        return
    (stderr_lines if msg.type in STDERR_CONSOLE_TYPES else stdout_lines).append(msg.text)


# --- 単体処理 --------------------------------------------------------
def build_page(page_html: str, src: str) -> str:
    """page_html の後でプログラムを `new Function(src)()` として 1 回実行するハーネス HTML を返す.

    ハーネスの script 要素は実行前に自身を DOM から取り除くため、実行後の DOM にプログラム本体は残らない。
    実行結果は `window.__hl_status` (`"ok"` / `"error"`) と `window.__hl_error` に格納する。

    Args:
        page_html: ベンチマークの page_html (無ければ空文字).
        src: 実行するプログラム.

    Returns:
        ハーネス HTML の内容。
    """
    src_literal = json.dumps(src).replace("<", "\\u003c")
    harness = (
        "<script>\n"
        "(() => {\n"
        "  document.currentScript.remove();\n"
        f"  const src = {src_literal};\n"
        "  try {\n"
        "    new Function(src)();\n"
        "    window.__hl_status = 'ok';\n"
        "  } catch (e) {\n"
        "    window.__hl_status = 'error';\n"
        "    window.__hl_error = String((e && e.stack) || e);\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )
    return f'<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n<body>\n{page_html}\n{harness}</body>\n</html>\n'


def _observe_page_once(browser, html: str, timeout_ms: int) -> dict:
    """ハーネス HTML を新規 BrowserContext で 1 回ロードして観測する (`observe_page` の 1 試行分).

    Args:
        browser: Playwright (sync API) の Browser.
        html: `build_page` で組み立てたハーネス HTML.
        timeout_ms: ロードのタイムアウト (ミリ秒).

    Returns:
        `observe_page` の戻り値から `attempts` を除いた辞書。
    """
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    failed_scripts: list[str] = []
    observation: dict = {"status": None, "error_head": None, "dom_sha256": None, "collected": None}

    start = time.perf_counter()
    context = browser.new_context()
    try:
        context.route(PAGE_URL, lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
        page = context.new_page()
        page.on("console", lambda msg: _route_console(msg, stdout_lines, stderr_lines))
        page.on("pageerror", lambda exc: stderr_lines.append(str(exc)))
        page.on("requestfailed", lambda req: failed_scripts.append(req.url) if req.resource_type == "script" else None)
        page.on("response", lambda resp: failed_scripts.append(resp.url) if resp.request.resource_type == "script" and resp.status >= 400 else None)
        page.goto(PAGE_URL, wait_until="load", timeout=timeout_ms)
        status, error = page.evaluate("() => [window.__hl_status, window.__hl_error]")
        if status == "ok":
            observation["status"] = "success"
            observation["dom_sha256"] = _sha256(page.evaluate("() => document.documentElement.outerHTML"))
            observation["collected"] = page.evaluate(COLLECT_JS)
        else:
            observation["status"] = "error"
            observation["error_head"] = str(error)[:STDERR_HEAD_LIMIT]
    except Exception as exc:
        msg = str(exc)
        observation["status"] = "timeout" if ("Timeout" in type(exc).__name__ or "timeout" in msg.lower()) else "error"
        observation["error_head"] = msg[:STDERR_HEAD_LIMIT]
    finally:
        # browser 死亡後は close 不能のため失敗は無視する
        try:
            context.close()
        except Exception:
            pass

    stdout_text = "\n".join(stdout_lines)
    stderr_text = "\n".join(stderr_lines)
    observation.update(
        stdout_sha256=_sha256(stdout_text),
        stderr_sha256=_sha256(stderr_text),
        stdout_head=stdout_text[:STDOUT_HEAD_LIMIT],
        stderr_head=stderr_text[:STDERR_HEAD_LIMIT],
        failed_scripts=sorted(set(failed_scripts)),
        elapsed=time.perf_counter() - start,
    )
    return observation


def observe_page(browser, html: str, timeout_ms: int = TIMEOUT_MS) -> dict:
    """ハーネス HTML を新規 BrowserContext でロードし、console 出力・DOM・`__hl_collect()` の結果を返す.

    ロード完了 (`load` イベント) の時点で観測する。 console は Node の stdout / stderr に倣って振り分け、
    捕捉されなかった例外 (`pageerror`) は stderr 側に加える。
    page_html の外部スクリプトの取得に失敗した試行 (通信失敗 / HTTP 4xx・5xx) は観測をやり直し、
    最大 `1 + SCRIPT_LOAD_RETRIES` 回試行して最後の試行の観測値を返す。

    Args:
        browser: Playwright (sync API) の Browser.
        html: `build_page` で組み立てたハーネス HTML.
        timeout_ms: 1 試行あたりのロードのタイムアウト (ミリ秒).

    Returns:
        `status` (`"success"` / `"error"` / `"timeout"`), `error_head`,
        `stdout_sha256`, `stderr_sha256`, `stdout_head`, `stderr_head`,
        `dom_sha256`, `collected`, `failed_scripts` (取得に失敗したスクリプト URL, ソート済み),
        `attempts`, `elapsed` を持つ辞書。 失敗時の観測項目は取得できた範囲のみ。
    """
    for attempt in range(1, SCRIPT_LOAD_RETRIES + 2):
        observation = _observe_page_once(browser, html, timeout_ms)
        if not observation["failed_scripts"]:
            break
    observation["attempts"] = attempt
    return observation


def equivalent_output_browser(browser, page_html: str, fast_code: str, slow_code: str) -> tuple[bool, str | None, dict, dict]:
    """2 つのプログラムをブラウザで実行し、console 出力が等価かどうかと理由を返す.

    観測値には Step 4 (`equivalent_dom`) で使う `dom_sha256` も含まれる。

    Args:
        browser: Playwright (sync API) の Browser.
        page_html: ベンチマークの page_html.
        fast_code: fast 側のプログラム (決定化済み).
        slow_code: slow 側のプログラム (決定化済み).

    Returns:
        `(等価か, 理由, fast の観測値, slow の観測値)` のタプル。
        等価なら理由は `None`、非等価なら `"verification_failed"` / `"stdout_mismatch"` / `"stderr_mismatch"`。
    """
    obs_fast = observe_page(browser, build_page(page_html, fast_code))
    obs_slow = observe_page(browser, build_page(page_html, slow_code))

    if obs_fast["status"] != "success" or obs_slow["status"] != "success":
        return False, "verification_failed", obs_fast, obs_slow
    if obs_fast["stdout_sha256"] != obs_slow["stdout_sha256"]:
        return False, "stdout_mismatch", obs_fast, obs_slow
    if obs_fast["stderr_sha256"] != obs_slow["stderr_sha256"]:
        return False, "stderr_mismatch", obs_fast, obs_slow
    return True, None, obs_fast, obs_slow


def observe_value_browser(browser, page_html: str, code: str) -> dict:
    """1 プログラムについて、変数名収集・計測コード生成・ブラウザ実行を行い、変数格納値の観測値を返す.

    Args:
        browser: Playwright (sync API) の Browser.
        page_html: ベンチマークの page_html.
        code: 対象プログラム (決定化済み).

    Returns:
        `names_status`, `instrument_status`, `run_status`, `dump_status`, `values` を持つ辞書
        (`hayalab.jsperf.equivalent.observe_value` と同形式)。 途中で失敗した場合、以降の項目は `None`。
    """
    observation: dict = {"names_status": None, "instrument_status": None, "run_status": None, "dump_status": None, "values": None}

    names = _variable_names(code)
    if names is None:
        observation["names_status"] = "parse_error"
        return observation
    observation["names_status"] = "ok"

    result = _instrument_value_code(code, names, "-")
    observation["instrument_status"] = result["status"]
    if result["status"] != "ok":
        return observation

    observed = observe_page(browser, build_page(page_html, result["code"]))
    observation["run_status"] = observed["status"]
    dump = observed["collected"]
    if observed["status"] != "success" or dump is None:
        return observation

    observation["dump_status"] = dump["status"]
    if dump["status"] == "ok":
        observation["values"] = {name: _hash_record(record) for name, record in dump["values"].items()}
    return observation


def equivalent_value_browser(browser, page_html: str, fast_code: str, slow_code: str) -> tuple[bool, str | None, dict, dict]:
    """2 つのプログラムをブラウザで実行し、終了時の変数格納値が等価かどうかと理由を返す.

    比較規則は `hayalab.jsperf.equivalent.equivalent_value` と同一。

    Args:
        browser: Playwright (sync API) の Browser.
        page_html: ベンチマークの page_html.
        fast_code: fast 側のプログラム (決定化済み).
        slow_code: slow 側のプログラム (決定化済み).

    Returns:
        `(等価か, 理由, fast の観測値, slow の観測値)` のタプル。
        等価なら理由は `None`、非等価なら `"verification_failed"` / `"variable_mismatch"`。
    """
    obs_fast = observe_value_browser(browser, page_html, fast_code)
    obs_slow = observe_value_browser(browser, page_html, slow_code)
    is_equivalent, reason = _compare_values(obs_fast, obs_slow)
    return is_equivalent, reason, obs_fast, obs_slow


def observe_completion_browser(browser, page_html: str, code: str) -> dict:
    """1 プログラムについて、計測コード生成・ブラウザ実行を行い、`eval` による完了値の観測値を返す.

    Args:
        browser: Playwright (sync API) の Browser.
        page_html: ベンチマークの page_html.
        code: 対象プログラム (決定化済み).

    Returns:
        `instrument_status`, `run_status`, `dump_status`, `value` を持つ辞書
        (`hayalab.jsperf.equivalent.observe_completion` と同形式)。
    """
    observation: dict = {"instrument_status": None, "run_status": None, "dump_status": None, "value": None}

    result = _instrument_completion_code(code, "-")
    observation["instrument_status"] = result["status"]
    if result["status"] != "ok":
        return observation

    observed = observe_page(browser, build_page(page_html, result["code"]))
    observation["run_status"] = observed["status"]
    dump = observed["collected"]
    if observed["status"] != "success" or dump is None:
        return observation

    observation["dump_status"] = dump["status"]
    if dump["status"] == "ok":
        observation["value"] = _hash_record(dump["value"])
    return observation


def equivalent_formula_browser(browser, page_html: str, fast_code: str, slow_code: str) -> tuple[bool, str | None, dict, dict]:
    """2 つのプログラムの完了値をブラウザで観測し、等価かどうかと理由を返す.

    比較対象・比較規則は `hayalab.jsperf.equivalent.equivalent_formula` と同一
    (比較できないペアは等価として扱う)。

    Args:
        browser: Playwright (sync API) の Browser.
        page_html: ベンチマークの page_html.
        fast_code: fast 側のプログラム (決定化済み).
        slow_code: slow 側のプログラム (決定化済み).

    Returns:
        `(等価か, 理由, fast の観測値, slow の観測値)` のタプル。
        等価なら理由は `None`、非等価なら `"completion_value_mismatch"`。
    """
    empty = {"instrument_status": None, "run_status": None, "dump_status": None, "value": None}
    if not is_completion_comparable(fast_code, slow_code):
        return True, None, {"comparable": False, **empty}, {"comparable": False, **empty}

    obs_fast = {"comparable": True, **observe_completion_browser(browser, page_html, fast_code)}
    obs_slow = {"comparable": True, **observe_completion_browser(browser, page_html, slow_code)}
    is_equivalent, reason = _compare_completion(obs_fast["value"], obs_slow["value"])
    return is_equivalent, reason, obs_fast, obs_slow


def equivalent_dom(obs_fast: dict, obs_slow: dict) -> tuple[bool, str | None]:
    """`observe_page` の観測値どうしで、実行後の DOM (`outerHTML`) が一致するかを返す.

    Args:
        obs_fast: fast 側の `observe_page` の観測値.
        obs_slow: slow 側の `observe_page` の観測値.

    Returns:
        `(等価か, 理由)`。 理由は `None` / `"dom_mismatch"`。
    """
    if obs_fast["dom_sha256"] != obs_slow["dom_sha256"]:
        return False, "dom_mismatch"
    return True, None
