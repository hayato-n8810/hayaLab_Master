// プログラムの完了値を書き出す計測コードを生成するスクリプト
// 引数で受け取った JS ファイル・書き出し先パスから、そのまま実行できる計測コードを
// {code, status} の JSON で stdout へ返す
// 書き出し先パスが "-" のときはブラウザ用に、ハッシュ化前の文字列を返す window.__hl_collect() を定義する
const fs = require("fs");

// プログラム本体を文字列として埋め込み、関数ラップ内の直接 eval で完了値を得る計測コード
// 終了時に完了値をハッシュ化して書き出す。program による書き換えに備え、記録処理が使う組み込みは先に退避する
function buildCode(source, dumpPath) {
  const browser = dumpPath === "-";
  const header = browser
    ? `const __hl_window = window;
function __hl_sha256(text) {
  return text;
}
`
    : `const __hl_process = process;
const __hl_fs = require("fs");
const __hl_crypto = require("crypto");
const __hl_dump_path = ${JSON.stringify(dumpPath)};
function __hl_sha256(text) {
  return __hl_crypto.createHash("sha256").update(text, "utf8").digest("hex");
}
`;
  const emit = browser
    ? `__hl_window.__hl_collect = __hl_collect;
`
    : `__hl_process.once("exit", function () {
  __hl_fs.writeFileSync(__hl_dump_path, __hl_stringify(__hl_collect()));
});
`;
  return `${header}const __hl_stringify = JSON.stringify;
const __hl_keys = Object.keys;
const __hl_isArray = Array.isArray;
const __hl_sort = Array.prototype.sort;
const __hl_source = ${JSON.stringify(source)};
function __hl_sorted_keys(key, value) {
  if (value === null || typeof value !== "object" || __hl_isArray(value)) return value;
  const keys = __hl_sort.call(__hl_keys(value));
  const sorted = {};
  for (let i = 0; i < keys.length; i++) sorted[keys[i]] = value[keys[i]];
  return sorted;
}
function __hl_record(value) {
  if (typeof value === "function") return null;
  let text;
  try {
    text = value.toString();
  } catch (e) {
    return null;
  }
  if (typeof text !== "string") return null;
  const record = { s_sha256: __hl_sha256(text) };
  if (text === "[object Object]") {
    try {
      const json = __hl_stringify(value.valueOf(), __hl_sorted_keys);
      if (typeof json === "string") record.v_sha256 = __hl_sha256(json);
    } catch (e) {}
  }
  return record;
}
var __hl_done = false;
var __hl_value;
function __hl_collect() {
  if (!__hl_done) return { status: "no_value" };
  return { status: "ok", value: __hl_record(__hl_value) };
}
${emit}(function () {
__hl_value = eval(__hl_source);
__hl_done = true;
})();
`;
}

const source = fs.readFileSync(process.argv[2], "utf8");
const dumpPath = process.argv[3];

try {
  process.stdout.write(JSON.stringify({ code: buildCode(source, dumpPath), status: "ok" }));
} catch (e) {
  process.stdout.write(JSON.stringify({ code: source, status: "generate_error" }));
}
