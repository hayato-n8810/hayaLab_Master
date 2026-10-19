// プログラム終了時の変数格納値を書き出す計測コードを生成する Babel 変換
// 引数で受け取った JS ファイル・名前一覧 (JSON 配列)・書き出し先パスから、
// そのまま実行できる計測コードを {code, status} の JSON で stdout へ返す
const fs = require("fs");
const { parse } = require("@babel/parser");
const generate = require("@babel/generator").default;

const PARSE_OPTIONS = {
  sourceType: "script",
  allowReturnOutsideFunction: true,
  allowAwaitOutsideFunction: true,
  errorRecovery: false,
};

// program.body 先頭へ挿入する、読み出し関数への参照を外へ渡す文
const EXPORT_NODES = parse("__hl_get = __hl_read;", { sourceType: "script" }).program.body;

// program.body 末尾へ追加する、名前ごとに同名変数の値を返す読み出し関数
function buildReaderNodes(names) {
  const cases = names.map((name) => `case ${JSON.stringify(name)}: return ${name};`).join("\n");
  const source = `function __hl_read(__hl_n) {\nswitch (__hl_n) {\n${cases}\n}\n}`;
  return parse(source, PARSE_OPTIONS).program.body;
}

// program より前に置く前置コード。終了時に名前ごとの値を読み出し、ハッシュ化して書き出す
// program による書き換えに備え、読み出し処理が使う組み込みは program より先に退避する
function buildPrelude(names, dumpPath) {
  return `const __hl_process = process;
const __hl_JSON = JSON;
const __hl_fs = require("fs");
const __hl_crypto = require("crypto");
const __hl_dump_path = ${JSON.stringify(dumpPath)};
const __hl_names = ${JSON.stringify(names)};
function __hl_sha256(text) {
  return __hl_crypto.createHash("sha256").update(text, "utf8").digest("hex");
}
var __hl_get;
__hl_process.once("exit", function () {
  if (typeof __hl_get !== "function") {
    __hl_fs.writeFileSync(__hl_dump_path, __hl_JSON.stringify({ status: "no_reader" }));
    return;
  }
  const values = {};
  for (const name of __hl_names) {
    let value;
    try {
      value = __hl_get(name);
    } catch (e) {
      continue;
    }
    if (typeof value === "function") continue;
    let text;
    try {
      text = value.toString();
    } catch (e) {
      continue;
    }
    if (typeof text !== "string") continue;
    const record = { s_sha256: __hl_sha256(text) };
    if (text === "[object Object]") {
      try {
        const json = __hl_JSON.stringify(value.valueOf());
        if (typeof json === "string") record.v_sha256 = __hl_sha256(json);
      } catch (e) {}
    }
    values[name] = record;
  }
  __hl_fs.writeFileSync(__hl_dump_path, __hl_JSON.stringify({ status: "ok", values: values }));
});
`;
}

const source = fs.readFileSync(process.argv[2], "utf8");
const names = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const dumpPath = process.argv[4];

let ast;
try {
  ast = parse(source, PARSE_OPTIONS);
} catch (e) {
  process.stdout.write(JSON.stringify({ code: source, status: "parse_error" }));
  process.exit(0);
}

try {
  ast.program.body = [...EXPORT_NODES, ...ast.program.body, ...buildReaderNodes(names)];
  const body = generate(ast, {}).code;
  const code = buildPrelude(names, dumpPath) + "(function () {\n" + body + "\n})();\n";
  process.stdout.write(JSON.stringify({ code: code, status: "ok" }));
} catch (e) {
  process.stdout.write(JSON.stringify({ code: source, status: "generate_error" }));
}
