/**
 * @name function
 * @description Detects performance implications.
 * @kind problem
 * @problem.severity warning
 * @id js/performance/sigse/18
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

from CallExpr forEachCall
where
  // forEachの呼び出しを検出
  isCallTo(forEachCall, "forEach") 

select forEachCall, "This contains performance implications."
