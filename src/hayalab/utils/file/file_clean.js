// コードの整形: 改行コードの標準化 → prettier → コメント除去 → 空行の除去 → prettier
// 単体で実行すると常駐ワーカーになる（1 行 1 要求 {code, remove_comments, remove_blank_lines} → 1 行 {status, reasons, code}）
const { parse } = require("@babel/parser");
const traverse = require("@babel/traverse").default;
const prettier = require("prettier");

const PARSE_BASE = { allowReturnOutsideFunction: true, allowAwaitOutsideFunction: true, errorRecovery: false };
const LINE_BREAK = /[\n\r\u2028\u2029]/;

// script として解析し，失敗したら module として解析する
function parseProgram(code) {
  try {
    return parse(code, { ...PARSE_BASE, sourceType: "script" });
  } catch (scriptError) {
    return parse(code, { ...PARSE_BASE, sourceType: "module" });
  }
}

// 改行コードの標準化 + prettier
async function formatCode(code) {
  return prettier.format(code.replace(/\r\n/g, "\n"), { filepath: "program.js" });
}

// 編集 {start, end, text} を適用する（編集範囲は重ならないこと）
function applyEdits(code, edits) {
  const parts = [];
  let pos = 0;
  for (const e of [...edits].sort((a, b) => a.start - b.start)) {
    parts.push(code.slice(pos, e.start), e.text);
    pos = e.end;
  }
  parts.push(code.slice(pos));
  return parts.join("");
}

// コメントを除去する（ブロックコメントは改行を含めば改行，含まなければ空白 1 つに置き換えて字句の連結を防ぐ）
function removeComments(code, ast) {
  const edits = (ast.comments || []).map((c) => ({
    start: c.start,
    end: c.end,
    text: c.type === "CommentLine" ? "" : LINE_BREAK.test(code.slice(c.start, c.end)) ? "\n" : " ",
  }));
  return applyEdits(code, edits);
}

// 空行（空白だけの行）を除去する．文字列・テンプレートリテラルの中の行は残す
function removeBlankLines(code, ast) {
  const literals = [];
  traverse(ast, {
    "TemplateLiteral|StringLiteral|DirectiveLiteral"(path) {
      literals.push([path.node.start, path.node.end]);
    },
  });
  const inLiteral = (pos) => literals.some(([s, e]) => s < pos && pos < e);
  const kept = [];
  let offset = 0;
  for (const line of code.split("\n")) {
    if (line.trim() !== "" || inLiteral(offset)) kept.push(line);
    offset += line.length + 1;
  }
  return kept.join("\n");
}

// 整形・コメント除去・空行の除去．{status, reasons, code} を返す（status: ok / format_error / parse_error）
async function codeClean(code, { remove_comments = true, remove_blank_lines = true } = {}) {
  const firstLine = (e) => String(e && e.message ? e.message : e).split("\n")[0].slice(0, 200);
  let current;
  try {
    current = await formatCode(code);
  } catch (e) {
    return { status: "format_error", reasons: [firstLine(e)], code: null };
  }
  try {
    if (remove_comments) {
      const ast = parseProgram(current);
      if (ast.comments && ast.comments.length > 0) current = await formatCode(removeComments(current, ast));
    }
    if (remove_blank_lines) current = await formatCode(removeBlankLines(current, parseProgram(current)));
  } catch (e) {
    return { status: "parse_error", reasons: [firstLine(e)], code: null };
  }
  return { status: "ok", reasons: [], code: current };
}

module.exports = { traverse, parseProgram, formatCode, applyEdits, removeComments, removeBlankLines, codeClean };

if (require.main === module) {
  (async () => {
    for await (const line of require("readline").createInterface({ input: process.stdin })) {
      const request = JSON.parse(line);
      process.stdout.write(JSON.stringify(await codeClean(request.code, request)) + "\n");
    }
  })();
}
