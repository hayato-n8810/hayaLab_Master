// 2 プログラムのトップレベル文を比較し、差分がちょうど 1 文ずつで両側とも式文かを判定する Babel スクリプト
// 引数で受け取った 2 つの JS ファイルから、{comparable, status} の JSON を stdout へ返す
const fs = require("fs");
const { parse } = require("@babel/parser");

const PARSE_OPTIONS = {
  sourceType: "script",
  allowReturnOutsideFunction: true,
  allowAwaitOutsideFunction: true,
  errorRecovery: false,
};

// program.body の各文のソース文字列とノード型
function topLevelStatements(path) {
  const source = fs.readFileSync(path, "utf8");
  const ast = parse(source, PARSE_OPTIONS);
  return ast.program.body.map((stmt) => ({ text: source.slice(stmt.start, stmt.end), type: stmt.type }));
}

let first;
let second;
try {
  first = topLevelStatements(process.argv[2]);
  second = topLevelStatements(process.argv[3]);
} catch (e) {
  process.stdout.write(JSON.stringify({ comparable: false, status: "parse_error" }));
  process.exit(0);
}

// 先頭一致と末尾一致 (先頭一致と重ならない範囲) を取り除いた残りを差分とする
const shorter = Math.min(first.length, second.length);
let prefix = 0;
while (prefix < shorter && first[prefix].text === second[prefix].text) prefix++;
let suffix = 0;
while (suffix < shorter - prefix && first[first.length - 1 - suffix].text === second[second.length - 1 - suffix].text) suffix++;

const comparable =
  first.length - prefix - suffix === 1 &&
  second.length - prefix - suffix === 1 &&
  first[prefix].type === "ExpressionStatement" &&
  second[prefix].type === "ExpressionStatement";
process.stdout.write(JSON.stringify({ comparable: comparable, status: "ok" }));
