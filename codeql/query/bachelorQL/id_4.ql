/**
 * @name function
 * @description Detects performance implications.
 * @kind problem
 * @problem.severity warning
 * @id js/performance/sigse/827
 * @tags performance
 *       maintainability
 */

import javascript

from CallExpr mapCall, CallExpr applyCall
where
  // 1. map呼び出しの対象が、apply呼び出しである
  mapCall.getCallee().(PropAccess).getBase() = applyCall and

  // 2. メソッド名がそれぞれ "map" と "apply" である
  mapCall.getCalleeName() = "map" and
  applyCall.getCalleeName() = "apply"

select mapCall, "This contains performance implications."

