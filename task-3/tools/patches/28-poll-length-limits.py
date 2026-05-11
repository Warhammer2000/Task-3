"""Patch 28: enforce Telegram poll length limits.

Bug found on RU quiz: poll option text and explanations got truncated with
"..." because Telegram has hard limits on sendPoll fields:

    InputPollOption.text       1-100 characters
    InputPoll.explanation      0-200 characters
    InputPoll.question         1-300 characters

The Examiner system prompt said "<=120 chars" for options and "2-4
sentences" for explanation. Sonnet 4.5 frequently produced options near
the 120 ceiling and explanations of 250+ chars, which Telegram silently
truncated mid-word.

Fix is three-layered:

1. **Prompt tightening** — options ≤ 95, explanation ≤ 195 (5-char safety
   margin under Telegram's hard ceilings). Applied to both Examiner
   instances: pick: build examiner body (slow-path) and pool: build
   examiner body.

2. **Runtime truncation** in parse-Examiner-JSON nodes — defensive layer
   that guarantees no Telegram error even if a future model/prompt drifts.
   Options > 95 truncated to 94 chars + "…". Explanation > 195 to 194 + "…".

3. **Pool reset** — existing pool entries were generated under the old
   120-char prompt and carry truncation-prone options. Delete them all
   (`DELETE FROM app.quiz_pool`) and the post-claim refill chain will
   regenerate fresh entries under the new prompt. Companion script
   `tools/warmup-pool.sh` accelerates the rebuild.
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# ============================================================
# 1. Tighten prompts in both Examiner-body builders
# ============================================================
OLD_FRAGMENT = (
    '\\"options\\": { \\"A\\": \\"<=120\\", \\"B\\": \\"<=120\\", \\"C\\": \\"<=120\\", \\"D\\": \\"<=120\\" }, '
    '\\"correctAnswer\\": \\"A\\"|\\"B\\"|\\"C\\"|\\"D\\", \\"explanation\\": \\"<2-4 sentences>\\"'
)
NEW_FRAGMENT = (
    '\\"options\\": { \\"A\\": \\"<=95 chars HARD limit\\", \\"B\\": \\"<=95 chars HARD limit\\", '
    '\\"C\\": \\"<=95 chars HARD limit\\", \\"D\\": \\"<=95 chars HARD limit\\" }, '
    '\\"correctAnswer\\": \\"A\\"|\\"B\\"|\\"C\\"|\\"D\\", '
    '\\"explanation\\": \\"<=195 chars HARD limit, 1-2 tight sentences only\\"'
)

EXTRA_DIRECTIVE = (
    "\\n\\nCRITICAL CHAR-LENGTH LIMITS (Telegram poll API enforces these — exceeding causes silent truncation that destroys meaning):\\n"
    "- Each option (A/B/C/D): MAX 95 characters. Count carefully. If your option would exceed, REPHRASE shorter, do NOT just cut.\\n"
    "- Explanation: MAX 195 characters total. One or two tight sentences. NO long compound clauses.\\n"
    "- Question stem: MAX 280 characters. (Already a guideline; restated for clarity.)\\n"
    "Sanity-check each field's char count before output. Better a slightly less detailed option that fits than a perfect one that gets truncated."
)

for n in nodes:
    if n.get('name') in ('pick: build examiner body', 'pool: build examiner body'):
        code = n['parameters'].get('jsCode', '')
        new_code = code.replace(OLD_FRAGMENT, NEW_FRAGMENT)
        # Add critical-limits directive after the JSON schema spec (before \"Calibrate difficulty\")
        marker = 'Calibrate difficulty against a senior backend engineer bar.'
        if EXTRA_DIRECTIVE.replace('\\n', '\n') not in new_code and marker in new_code:
            # Inject extra directive in the system prompt string. The system prompt is a JS string
            # literal. Append directive before "Calibrate difficulty" sentence.
            new_code = new_code.replace(
                marker,
                EXTRA_DIRECTIVE.replace('\\"', '\\\\"') + '\\n\\n' + marker
            )
        if new_code != code:
            n['parameters']['jsCode'] = new_code
            sys.stderr.write(f"Tightened prompt in: {n['name']}\n")
        else:
            sys.stderr.write(f"WARN: no change to {n['name']} (fragment not found)\n")

# ============================================================
# 2. Runtime truncation in parse-Examiner-JSON
# ============================================================
def add_truncation(code, source_node_name):
    """Insert defensive truncation right after `parsed` is set + verified to have questions."""
    truncation_block = """
// Defensive truncation — Telegram sendPoll hard limits: option=100, explanation=200.
// Use 95/195 with "…" indicator so we don't bump into the ceiling.
function truncWithEllipsis(s, maxLen) {
  const str = String(s || '');
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 1) + '…';
}
parsed.questions = parsed.questions.map(q => {
  const fixedOptions = {};
  for (const letter of ['A','B','C','D']) {
    fixedOptions[letter] = truncWithEllipsis(q.options?.[letter] || '', 95);
  }
  return {
    ...q,
    question: truncWithEllipsis(q.question || '', 280),
    options: fixedOptions,
    explanation: truncWithEllipsis(q.explanation || '', 195)
  };
});
"""
    # Insert right after `if (!Array.isArray(...)` validation block
    marker = "if (!Array.isArray(parsed?.questions)"
    idx = code.find(marker)
    if idx < 0:
        return code, False
    # Find the closing `}` of the throw block, then insert truncation right after
    # Easier: find the next `}` line after marker
    after_idx = code.find('}', idx)
    if after_idx < 0:
        return code, False
    # Find newline after `}`
    nl_idx = code.find('\n', after_idx)
    if nl_idx < 0:
        nl_idx = after_idx + 1
    return code[:nl_idx+1] + truncation_block + code[nl_idx+1:], True

for n in nodes:
    if n.get('name') in ('pick: parse Examiner JSON', 'pool: parse Examiner JSON'):
        code = n['parameters'].get('jsCode', '')
        if 'truncWithEllipsis' in code:
            sys.stderr.write(f"Skipped {n['name']} (already has truncation)\n")
            continue
        new_code, ok = add_truncation(code, n['name'])
        if ok:
            n['parameters']['jsCode'] = new_code
            sys.stderr.write(f"Added runtime truncation to: {n['name']}\n")
        else:
            sys.stderr.write(f"WARN: could not find insertion point in {n['name']}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
