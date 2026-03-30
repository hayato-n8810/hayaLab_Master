/**
 * @name function
 * @description Detects performance implications.
 * @kind problem
 * @problem.severity warning
 * @id js/performance/sigse/222
 * @tags performance
 *       maintainability
 */

import javascript

/**
 * for-in 文の本体内に，
 * 条件式として hasOwnProperty 呼び出しを含む if 文が存在するかを判定する述語
 */
predicate forInWithIfhasOwnProperty(ForInStmt f) {
  exists(IfStmt ifStmt |
    // if 文が for-in 文の本体の子孫
    f.getBody().getAChild*() = ifStmt and
    // if 条件式内に hasOwnProperty 呼び出しが存在
    exists(CallExpr c |
      c = ifStmt.getCondition().getAChild*() and
      c.getCallee().(PropAccess).getPropertyName() = "hasOwnProperty"
    )
  )
}

from ForInStmt f
where forInWithIfhasOwnProperty(f)
select f, "This performance implications."