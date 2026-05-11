"""Patch 31: build /learn INSERT SQL in upstream Code node, bypass queryReplacement.

Patch 30 switched to PostgreSQL parameter binding via n8n's
queryReplacement option. It worked for chat_id/url/title/content (text
values) but failed on the JSONB column with:

    invalid input syntax for type json. Token "??" is invalid.

The `??` is PostgreSQL's printable representation of two unrecognised
bytes — most likely a UTF-8 multi-byte character was cut mid-sequence
during n8n→postgres parameter encoding. Cyrillic strings in the summary
made this manifest.

The bulletproof approach: build the entire SQL string in JavaScript
inside the parse-Teacher-JSON node, applying proper single-quote
escaping in JS context (no n8n expression engine, no parameter binding,
no mid-byte cuts). Then the Postgres node just executes the prebuilt SQL
verbatim.

This is the same pattern used for the Anthropic Teacher/Examiner request
bodies (built in upstream Code node, sent via HTTP Request as a single
string) — proven to handle arbitrary text content safely.
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# Re-dump fresh from DB since the in-memory copy may be stale
import subprocess
subprocess.run(
    "docker exec task3-postgres bash -c "
    "\"psql -U n8n -d n8n -t -A -c 'SELECT nodes FROM workflow_history "
    "WHERE \\\"versionId\\\" = ''215e62ce-2317-4940-acfa-42f294c0810a'';' "
    "> /tmp/db_nodes.json\" && docker cp task3-postgres:/tmp/db_nodes.json C:/tmp/db_nodes.json",
    shell=True, check=False
)

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# ============================================================
# 1. Augment /learn: parse Teacher JSON to build insert_sql
# ============================================================
# Find current parse Teacher JSON jsCode
for n in nodes:
    if n.get('name') == '/learn: parse Teacher JSON':
        cur = n['parameters']['jsCode']
        # Look for the return statement — we'll prepend SQL building before it
        if 'insert_sql' in cur:
            sys.stderr.write("Skipped /learn: parse Teacher JSON (already builds SQL)\n")
            continue
        # Find `return [{ json: { ... } }];` and replace with SQL-building version
        # The existing return is at the bottom. Construct new version.
        # We'll just rewrite the whole node deterministically.
        new_js = r"""const mat = $('/learn: extract title+body').item.json;
const response = $input.first().json;
const rawText = response?.content?.[0]?.text || '';

let parsed;
try {
  const cleaned = rawText.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim();
  parsed = JSON.parse(cleaned);
} catch (err) {
  throw new Error('Teacher returned unparseable JSON: ' + rawText.slice(0, 300));
}

// Validate required fields per the Teacher prompt's schema
const requiredFields = ['title', 'key_points', 'main_concepts', 'difficulty'];
for (const f of requiredFields) {
  if (!(f in parsed)) throw new Error('Teacher output missing: ' + f);
}
if (!Array.isArray(parsed.key_points) || parsed.key_points.length < 5 || parsed.key_points.length > 7) {
  throw new Error('key_points must have 5-7 items, got ' + (parsed.key_points || []).length);
}
if (!Array.isArray(parsed.main_concepts) || parsed.main_concepts.length === 0) {
  throw new Error('main_concepts must be a non-empty array');
}
const validDifficulty = ['beginner', 'intermediate', 'advanced'];
if (!validDifficulty.includes(parsed.difficulty)) {
  throw new Error('difficulty must be beginner|intermediate|advanced, got: ' + parsed.difficulty);
}

const title = String(parsed.title || mat.title || 'Untitled').slice(0, 200);

// Build INSERT SQL in JS context — bulletproof escaping, no n8n template engine,
// no parameter binding (which mangled UTF-8 in queryReplacement path).
function esc(s) {
  // SQL single-quote escape, also strip NUL chars that postgres rejects
  return String(s == null ? '' : s).replace(/\0/g, '').replace(/'/g, "''");
}

const summaryJson = JSON.stringify({
  key_points: parsed.key_points,
  main_concepts: parsed.main_concepts,
  difficulty: parsed.difficulty,
  interview_angle: parsed.interview_angle || ''
});

const insert_sql = `INSERT INTO app.learning_materials (chat_id, url, title, content, summary_json, difficulty)
VALUES (
  ${mat.chat_id},
  '${esc(mat.url)}',
  '${esc(title)}',
  '${esc(mat.content)}',
  '${esc(summaryJson)}'::jsonb,
  '${esc(parsed.difficulty)}'
)
ON CONFLICT (chat_id, url) DO UPDATE SET
  title = EXCLUDED.title,
  content = EXCLUDED.content,
  summary_json = EXCLUDED.summary_json,
  difficulty = EXCLUDED.difficulty,
  added_at = now()
RETURNING id, chat_id, url, title, summary_json, difficulty;`;

return [{ json: {
  chat_id: mat.chat_id,
  url: mat.url,
  title,
  content: mat.content,
  difficulty: parsed.difficulty,
  summary_json: JSON.parse(summaryJson),
  insert_sql
} }];"""
        n['parameters']['jsCode'] = new_js
        sys.stderr.write("Rewrote /learn: parse Teacher JSON to build insert_sql\n")

# ============================================================
# 2. Update /learn: pg INSERT material to use insert_sql verbatim
# ============================================================
for n in nodes:
    if n.get('name') == '/learn: pg INSERT material':
        n['parameters']['query'] = "={{ $json.insert_sql }}"
        # Clear queryReplacement
        if 'queryReplacement' in n['parameters'].get('options', {}):
            del n['parameters']['options']['queryReplacement']
        sys.stderr.write("Updated /learn: pg INSERT material to use $json.insert_sql\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
