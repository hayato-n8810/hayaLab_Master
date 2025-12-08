// babelでAST生成
const { parse } = require('@babel/parser');
const options = {
    sourceType: 'module',
    plugins: ['estree']
};
const fs = require('fs');
const code = fs.readFileSync(process.argv[2], 'utf8');
const ast = parse(code, options);
console.log(JSON.stringify(ast));