/**
 * @name function
 * @description Detects performance implications.
 * @kind problem
 * @problem.severity warning
 * @id js/performance/sigse/11
 * @tags performance
 *       maintainability
 */

import javascript

/**
 * 指定されたメソッド名を持つ呼び出し式を検出する述語
 */
predicate isCallTo(CallExpr call, string methodName) {
  call.getCallee().(PropAccess).getPropertyName() = methodName
}

from CallExpr parseCall, CallExpr stringifyCall
where
  // JSON.parse(JSON.stringify(...))を検出
  isCallTo(parseCall, "parse") and
  isCallTo(stringifyCall, "stringify") and
  // stringifyの呼び出しが、parseの引数になっていることを確認
  parseCall.getAnArgument() = stringifyCall 

select parseCall, "This contains performance implications."

