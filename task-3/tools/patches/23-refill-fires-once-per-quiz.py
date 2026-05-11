"""Patch 23: pool refill trigger fires once per quiz start, not per poll.

Bug from patch 21:
  pick: pg INSERT quiz_polls -> pick: trigger pool refill

But `pick: pg INSERT quiz_polls` is shared between:
  - initial pick chain (Q1):
      pick: pg INSERT quiz [from pool|slow] -> build poll body -> send poll
        -> capture poll_id -> pg INSERT quiz_polls
  - subsequent poll_ans chain (Q2..Q5):
      poll_ans: build next poll body -> pick: send poll -> capture poll_id
        -> pg INSERT quiz_polls

So the refill trigger fires 5 times per quiz session (once for Q1 + 4 for
Q2-Q5). The Q2-Q5 firings throw ExpressionError because the poll_ans path
never executes `pick: pg load material`, but the refill body references
`$('pick: pg load material').item.json.material_id`.

Fix: move refill trigger up. Fire it from BOTH `pick: pg INSERT quiz`
(slow path) AND `pick: pg INSERT quiz from pool` (fast path) as a parallel
sibling of `pick: build poll body`. Both nodes only execute on initial
quiz creation, never during poll_ans.

Tradeoff: parallel sibling means n8n executes the depth-first subtree of
one branch fully before the other (per the patch 19 lesson). Refill is a
single fast HTTP call (~50ms response), so the order doesn't matter for
user-perceived latency.
"""
import json, sys

with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# Remove old wiring
if 'pick: pg INSERT quiz_polls' in connections:
    # Was wired to pick: trigger pool refill; clear that out (becomes terminal)
    connections['pick: pg INSERT quiz_polls'] = {"main": [[]]}
    sys.stderr.write("Removed pick: pg INSERT quiz_polls -> trigger pool refill (was buggy)\n")

# Add refill as parallel sibling of build poll body on slow-path
slow_targets = connections.get('pick: pg INSERT quiz', {}).get('main', [[]])
if slow_targets and slow_targets[0]:
    has_refill = any(t.get('node') == 'pick: trigger pool refill' for t in slow_targets[0])
    if not has_refill:
        slow_targets[0].append({"node": "pick: trigger pool refill", "type": "main", "index": 0})
        connections.setdefault('pick: pg INSERT quiz', {})['main'] = slow_targets
        sys.stderr.write("Wired slow-path pg INSERT quiz -> + pick: trigger pool refill\n")

# Add refill as parallel sibling on fast-path
fast_targets = connections.get('pick: pg INSERT quiz from pool', {}).get('main', [[]])
if fast_targets and fast_targets[0]:
    has_refill = any(t.get('node') == 'pick: trigger pool refill' for t in fast_targets[0])
    if not has_refill:
        fast_targets[0].append({"node": "pick: trigger pool refill", "type": "main", "index": 0})
        connections.setdefault('pick: pg INSERT quiz from pool', {})['main'] = fast_targets
        sys.stderr.write("Wired fast-path pg INSERT quiz from pool -> + pick: trigger pool refill\n")

with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
