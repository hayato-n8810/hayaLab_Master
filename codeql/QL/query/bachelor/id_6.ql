/**
 * @name function
 * @description Detects performance implications.
 * @kind problem
 * @problem.severity warning
 * @id js/performance/sigse/874
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

from ForOfStmt f, CallExpr pushCall
where
    // for-of内のpushの呼び出しを検出
    isCallTo(pushCall, "push") and
    f.getBody().getAChildStmt*().getAChildExpr*() = pushCall

select f, "This contains performance implications."
