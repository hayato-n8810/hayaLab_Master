/**
 * @name function
 * @description Detects performance implications.
 * @kind problem
 * @problem.severity warning
 * @id js/performance/sigse/10
 * @tags performance
 *       maintainability
 */

import javascript

// 任意のノードの子孫にForInStmtがあるかどうかをチェックする述語
from ForInStmt f
select f, "This contains performance implications."
