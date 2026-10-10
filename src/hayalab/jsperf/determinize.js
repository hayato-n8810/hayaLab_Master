// プログラム中の非決定的な API を決定化する Babel 変換
// 引数で受け取った JS ファイルを変換し、{code, status} を JSON で stdout へ返す
const fs = require("fs");
const { parse } = require("@babel/parser");
const generate = require("@babel/generator").default;

const PARSE_OPTIONS = {
  sourceType: "script",
  allowReturnOutsideFunction: true,
  allowAwaitOutsideFunction: true,
  errorRecovery: false,
};

// 決定化に用いる値は呼び出し側 (Python) が argv で渡す
const RANDOM_VALUE = Number(process.argv[3]);
const FIXED_TIMESTAMP = Number(process.argv[4]);

// program.body 先頭へ挿入する上書き文。起動時に 1 度だけ AST 化する
// 対象をプログラム側が同名で宣言していると巻き上げで undefined になるため、
// いずれの上書きも typeof ガードで包む
const STUB_SOURCE = `
if (typeof Math !== "undefined" && Math) {
  Math.random = function () { return ${RANDOM_VALUE}; };
}
if (typeof Date !== "undefined" && Date) {
  Date.now = function () { return ${FIXED_TIMESTAMP}; };
}
if (typeof performance !== "undefined" && performance) {
  performance.now = function () { return 0; };
}
if (typeof console !== "undefined" && console) {
  console.time = function () {};
  console.timeLog = function (label) {
    console.log((label === undefined ? "default" : label) + ": 0ms");
  };
  console.timeEnd = function (label) {
    console.log((label === undefined ? "default" : label) + ": 0ms");
  };
}
`;

const STUB_NODES = parse(STUB_SOURCE, { sourceType: "script" }).program.body;

// 引数なしの new Date() へ固定タイムスタンプを与える
function rewriteNewDate(root) {
  const stack = [root];
  while (stack.length > 0) {
    const node = stack.pop();
    if (!node || typeof node !== "object") continue;
    if (Array.isArray(node)) {
      for (const child of node) stack.push(child);
      continue;
    }
    if (typeof node.type !== "string") continue;
    if (
      node.type === "NewExpression" &&
      node.callee &&
      node.callee.type === "Identifier" &&
      node.callee.name === "Date" &&
      node.arguments.length === 0
    ) {
      node.arguments.push({ type: "NumericLiteral", value: FIXED_TIMESTAMP });
    }
    for (const key of Object.keys(node)) {
      if (key === "loc" || key === "start" || key === "end") continue;
      const value = node[key];
      if (value && typeof value === "object") stack.push(value);
    }
  }
}

const source = fs.readFileSync(process.argv[2], "utf8");

let ast;
try {
  ast = parse(source, PARSE_OPTIONS);
} catch (e) {
  process.stdout.write(JSON.stringify({ code: source, status: "parse_error" }));
  process.exit(0);
}

try {
  rewriteNewDate(ast.program);
  ast.program.body = [...STUB_NODES, ...ast.program.body];
  const code = generate(ast, {}).code;
  process.stdout.write(JSON.stringify({ code: code, status: "ok" }));
} catch (e) {
  process.stdout.write(JSON.stringify({ code: source, status: "generate_error" }));
}
