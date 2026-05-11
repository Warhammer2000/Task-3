"""Patch 21: quiz pool architecture — pre-generated quizzes for instant /quiz response.

ARCHITECTURE
============

1. New table `app.quiz_pool` (created via SQL migration, not this patch):
     id, material_id, lang, questions JSONB, generated_at, generation_model

2. Pool refill workflow (new Webhook trigger + chain):
     /webhook/pool-refill receives {material_id, lang}.
     Responds 200 immediately (fire-and-forget caller pattern).
     Counts existing pool entries for this material+lang.
     If < 3, generates ONE new quiz via Examiner (Sonnet 4.6) with
     temperature 0.9 + prior-stems uniqueness directive.
     Inserts into pool.
     If still < 3, fires itself again (self-propagating refill).

3. Pick callback fast path:
     pg load material → lang load →
     pg claim from pool (DELETE ... RETURNING via subquery+SKIP LOCKED) →
     normalize claim result →
     IF claimed?
       TRUE  (fast): → pg INSERT quiz from pool → existing build poll Q1 ...
       FALSE (slow): → existing ack → Examiner → ...
     Both paths converge at pick: build poll body.

4. After material insert in /learn, trigger initial pool fill via refill webhook.

5. After each pick claim (fast or slow path), trigger top-up refill.

6. Examiner model upgrade: Haiku 4.5 → Sonnet 4.6 (better question quality;
   speed acceptable since pool runs in background).

SAFETY
======
- Concurrency-safe pool claim via `FOR UPDATE SKIP LOCKED` — two users on
  same material won't claim same pool entry.
- Pool generation isolated in separate webhook chain — failures don't
  affect main user flow.
- Slow-path fallback unchanged — pool empty → existing Examiner path.
- Schema migration runs idempotently (CREATE TABLE IF NOT EXISTS).
"""
import json, sys, uuid

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# Find Postgres credentials
PG_CREDS = None
for n in nodes:
    if n.get('type','').endswith('postgres') and n.get('credentials'):
        PG_CREDS = n['credentials']
        break

def new_id():
    return str(uuid.uuid4())

# ============================================================
# Examiner model — upgrade Haiku → Sonnet 4.6 in pick: build examiner body
# ============================================================
for n in nodes:
    if n.get('name') == 'pick: build examiner body':
        code = n['parameters'].get('jsCode','')
        # Replace haiku model name with sonnet
        new_code = code.replace("'claude-haiku-4-5-20251001'", "'claude-sonnet-4-5'")
        new_code = new_code.replace("'claude-haiku-4-5'", "'claude-sonnet-4-5'")
        if new_code != code:
            n['parameters']['jsCode'] = new_code
            sys.stderr.write("Upgraded slow-path Examiner: Haiku 4.5 -> Sonnet 4.5\n")

# ============================================================
# Pool: webhook trigger
# ============================================================
pool_webhook = {
    "parameters": {
        "httpMethod": "POST",
        "path": "pool-refill",
        "responseMode": "responseNode",
        "options": {}
    },
    "type": "n8n-nodes-base.webhook",
    "typeVersion": 2,
    "position": [-1400, 1600],
    "id": new_id(),
    "name": "pool: webhook /pool-refill",
    "webhookId": new_id()
}

pool_respond_immediately = {
    "parameters": {
        "respondWith": "text",
        "responseBody": "OK",
        "options": {"responseHeaders": {"entries": [{"name": "Content-Type", "value": "text/plain"}]}}
    },
    "type": "n8n-nodes-base.respondToWebhook",
    "typeVersion": 1.1,
    "position": [-1200, 1600],
    "id": new_id(),
    "name": "pool: respond OK"
}

# Pool count + IF gate (only generate if < 3)
POOL_COUNT_SQL = (
    "SELECT COUNT(*)::INT AS pool_count\n"
    "FROM app.quiz_pool\n"
    "WHERE material_id = {{ Number($('pool: webhook /pool-refill').item.json.body.material_id) }}\n"
    "  AND lang = '{{ ($('pool: webhook /pool-refill').item.json.body.lang || 'en').replace(/[^a-z]/g,'') }}';"
)
pool_count = {
    "parameters": {"operation": "executeQuery", "query": POOL_COUNT_SQL, "options": {}},
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [-1000, 1600],
    "id": new_id(),
    "name": "pool: pg count",
    "credentials": PG_CREDS
}

pool_count_check = {
    "parameters": {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{
                "id": "c-pool-needs-fill",
                "leftValue": "={{ $json.pool_count }}",
                "rightValue": 3,
                "operator": {"type": "number", "operation": "lt"}
            }],
            "combinator": "and"
        },
        "options": {}
    },
    "type": "n8n-nodes-base.if",
    "typeVersion": 2,
    "position": [-800, 1600],
    "id": new_id(),
    "name": "pool: needs fill?"
}

# Load material + summary
POOL_LOAD_MAT_SQL = (
    "SELECT m.id AS material_id, m.title, m.content, m.summary_json, m.difficulty\n"
    "FROM app.learning_materials m\n"
    "WHERE m.id = {{ Number($('pool: webhook /pool-refill').item.json.body.material_id) }};"
)
pool_load_mat = {
    "parameters": {"operation": "executeQuery", "query": POOL_LOAD_MAT_SQL, "options": {}},
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [-600, 1500],
    "id": new_id(),
    "name": "pool: pg load material",
    "credentials": PG_CREDS
}

# Load prior question stems (for uniqueness directive)
POOL_LOAD_STEMS_SQL = (
    "SELECT COALESCE(string_agg(stem, E'\\n'), '') AS prior_stems\n"
    "FROM (\n"
    "  SELECT jsonb_array_elements(questions->'questions')->>'question' AS stem\n"
    "  FROM app.quiz_pool\n"
    "  WHERE material_id = {{ Number($('pool: webhook /pool-refill').item.json.body.material_id) }}\n"
    "    AND lang = '{{ ($('pool: webhook /pool-refill').item.json.body.lang || 'en').replace(/[^a-z]/g,'') }}'\n"
    "  ORDER BY generated_at DESC LIMIT 20\n"
    ") t;"
)
pool_load_stems = {
    "parameters": {"operation": "executeQuery", "query": POOL_LOAD_STEMS_SQL, "options": {}},
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [-400, 1500],
    "id": new_id(),
    "name": "pool: pg load prior stems",
    "credentials": PG_CREDS
}

# Build Examiner body for pool gen
POOL_BUILD_BODY_JS = r"""// Build Anthropic Examiner request body for pool quiz generation
const mat = $('pool: pg load material').item.json;
const lang = ($('pool: webhook /pool-refill').item.json.body.lang || 'en').replace(/[^a-z]/g,'') || 'en';
const priorStems = $('pool: pg load prior stems').item.json.prior_stems || '';

const langDirective = lang === 'ru'
  ? '\n\nAll output strings (question, options A/B/C/D, explanation) must be in Russian. Answer letters stay A/B/C/D.'
  : '';

const uniqueDirective = priorStems
  ? `\n\nUNIQUENESS REQUIREMENT (CRITICAL): These question stems have ALREADY been generated for this material in prior quizzes:\n---\n${priorStems}\n---\nYour 5 new questions MUST cover DIFFERENT angles / concepts / failure modes. Do NOT paraphrase or rephrase any of the above. Pick fresh angles from the material.`
  : '';

let systemPrompt = "You are the Examiner in an AI-powered learning assistant for senior backend engineers preparing for staff-tier interviews. Given a material title, summary, and full content, generate EXACTLY 5 multiple-choice questions that probe whether the reader internalized the material at senior interview level.\n\nSTYLE non-negotiable:\n1. NO trivia. No year/acronym recall.\n2. PROBE understanding: apply concept to scenario, compare approaches, identify failure mode, spot what breaks if assumption changes.\n3. INTERVIEW FRAMING: phrase as interviewer would speak it.\n4. PLAUSIBLE DISTRACTORS: wrong options represent real misconceptions.\n5. ONE CORRECT ANSWER each (single best answer).\n6. EXPLANATIONS MUST TEACH why right is right AND why distractors are wrong.\n7. NO HARDCODING.\n\nOutput JSON with EXACTLY this schema:\n{\n  \"questions\": [\n    { \"id\": \"Q1\", \"question\": \"<=280 chars\", \"options\": { \"A\": \"<=120\", \"B\": \"<=120\", \"C\": \"<=120\", \"D\": \"<=120\" }, \"correctAnswer\": \"A\"|\"B\"|\"C\"|\"D\", \"explanation\": \"<2-4 sentences>\" }, ...Q2-Q5\n  ]\n}\n\nExactly 5 questions, IDs Q1-Q5, 4 options A-D each, correctAnswer single A-D letter. Distribute correct answers across A/B/C/D.\n\nOutput ONLY the JSON. No fences, no commentary.";

systemPrompt += langDirective;
systemPrompt += uniqueDirective;

const summary = mat.summary_json || {};
const keyPoints = Array.isArray(summary.key_points) ? summary.key_points.join('\n') : '';
const concepts = Array.isArray(summary.main_concepts) ? summary.main_concepts.join(', ') : '';
const userContent = 'TITLE: ' + (mat.title || '') + '\nDIFFICULTY: ' + (mat.difficulty || '') + '\n\nKEY POINTS:\n' + keyPoints + '\n\nCONCEPTS: ' + concepts + '\n\nFULL CONTENT:\n' + (mat.content || '');

const examiner_body = JSON.stringify({
  model: 'claude-sonnet-4-5',
  max_tokens: 3500,
  temperature: 0.9,  // higher temp -> question variety across pool entries
  system: systemPrompt,
  messages: [{ role: 'user', content: userContent }]
});

return [{ json: { ...mat, lang, examiner_body, generation_model: 'claude-sonnet-4-5' } }];"""

pool_build_body = {
    "parameters": {"jsCode": POOL_BUILD_BODY_JS},
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [-200, 1500],
    "id": new_id(),
    "name": "pool: build examiner body"
}

# Anthropic Examiner call
pool_examiner = {
    "parameters": {
        "method": "POST",
        "url": "https://api.anthropic.com/v1/messages",
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "anthropic-version", "value": "2023-06-01"},
            {"name": "x-api-key", "value": "={{ $env.ANTHROPIC_API_KEY }}"},
            {"name": "content-type", "value": "application/json"}
        ]},
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ $json.examiner_body }}",
        "options": {"timeout": 90000}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [0, 1500],
    "id": new_id(),
    "name": "pool: Examiner (Sonnet)"
}

# Parse + Fisher-Yates shuffle (same as pick: parse Examiner JSON)
POOL_PARSE_JS = r"""const mat = $('pool: build examiner body').item.json;
const response = $input.first().json;
const rawText = response?.content?.[0]?.text || '';

let parsed;
try {
  const cleaned = rawText.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim();
  parsed = JSON.parse(cleaned);
} catch (err) {
  throw new Error('Pool Examiner returned unparseable JSON: ' + rawText.slice(0, 300));
}

if (!Array.isArray(parsed?.questions) || parsed.questions.length !== 5) {
  throw new Error('Pool Examiner did not return exactly 5 questions');
}

// Fisher-Yates shuffle on option letter mapping to randomize correct answer slot
const letters = ['A','B','C','D'];
const shuffled = parsed.questions.map((q, qi) => {
  const origOpts = q.options || {};
  const optEntries = letters.map(L => ({ letter: L, text: origOpts[L] || '' }));
  // shuffle
  for (let i = optEntries.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [optEntries[i], optEntries[j]] = [optEntries[j], optEntries[i]];
  }
  // rebuild options keyed by new letter; remember which slot was correct
  const newOpts = {};
  let newCorrect = null;
  optEntries.forEach((e, i) => {
    const newLetter = letters[i];
    newOpts[newLetter] = e.text;
    if (e.letter === q.correctAnswer) newCorrect = newLetter;
  });
  return { ...q, options: newOpts, correctAnswer: newCorrect || q.correctAnswer };
});

return [{ json: { ...mat, questions: { questions: shuffled }, generation_model: mat.generation_model } }];"""

pool_parse = {
    "parameters": {"jsCode": POOL_PARSE_JS},
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [200, 1500],
    "id": new_id(),
    "name": "pool: parse Examiner JSON"
}

# Insert into quiz_pool
POOL_INSERT_SQL = (
    "INSERT INTO app.quiz_pool (material_id, lang, questions, generation_model)\n"
    "VALUES (\n"
    "  {{ $json.material_id }},\n"
    "  '{{ $json.lang.replace(/'/g, \"''\") }}',\n"
    "  '{{ JSON.stringify($json.questions).replace(/'/g, \"''\") }}'::jsonb,\n"
    "  '{{ ($json.generation_model || 'unknown').replace(/'/g, \"''\") }}'\n"
    ")\n"
    "RETURNING id, material_id, lang;"
)
pool_insert = {
    "parameters": {"operation": "executeQuery", "query": POOL_INSERT_SQL, "options": {}},
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [400, 1500],
    "id": new_id(),
    "name": "pool: pg INSERT pool entry",
    "credentials": PG_CREDS
}

# Self-fire refill (if more needed)
POOL_SELF_FIRE_BODY = (
    "={{ JSON.stringify({"
    " material_id: $('pool: pg load material').item.json.material_id,"
    " lang: $('pool: webhook /pool-refill').item.json.body.lang || 'en'"
    " }) }}"
)
pool_self_fire = {
    "parameters": {
        "method": "POST",
        "url": "=https://seniorprepcoach.ngrok.dev/webhook/pool-refill",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": POOL_SELF_FIRE_BODY,
        "options": {"timeout": 5000, "redirect": {"redirect": {}}}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [600, 1500],
    "id": new_id(),
    "name": "pool: self-fire next"
}

# Add all pool nodes
pool_nodes = [
    pool_webhook, pool_respond_immediately, pool_count, pool_count_check,
    pool_load_mat, pool_load_stems, pool_build_body, pool_examiner,
    pool_parse, pool_insert, pool_self_fire
]
nodes.extend(pool_nodes)
sys.stderr.write(f"Added {len(pool_nodes)} pool nodes\n")

# ============================================================
# Pick fast-path nodes
# ============================================================
# pg claim from pool: atomic DELETE...RETURNING via subquery with SKIP LOCKED
PICK_CLAIM_SQL = (
    "DELETE FROM app.quiz_pool\n"
    "WHERE id = (\n"
    "  SELECT id FROM app.quiz_pool\n"
    "  WHERE material_id = {{ $('pick: pg load material').item.json.material_id }}\n"
    "    AND lang = '{{ ($('lang: pg load pick').item.json.lang || 'en').replace(/'/g, \"''\") }}'\n"
    "  ORDER BY generated_at ASC\n"
    "  LIMIT 1\n"
    "  FOR UPDATE SKIP LOCKED\n"
    ")\n"
    "RETURNING id AS pool_id, material_id, lang, questions;"
)
pick_claim = {
    "parameters": {"operation": "executeQuery", "query": PICK_CLAIM_SQL, "options": {}},
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [-400, 800],
    "id": new_id(),
    "name": "pick: pg claim from pool",
    "credentials": PG_CREDS,
    "alwaysOutputData": True
}

# Normalize claim result via Code node (ensures single item with claimed: bool)
PICK_NORMALIZE_JS = r"""const rows = $input.all();
if (rows.length > 0 && rows[0].json.pool_id) {
  const r = rows[0].json;
  return [{ json: {
    claimed: true,
    pool_id: r.pool_id,
    material_id: r.material_id,
    lang: r.lang,
    questions: r.questions,
    chat_id: $('pick: pg load material').item.json.chat_id
  } }];
}
return [{ json: { claimed: false, chat_id: $('pick: pg load material').item.json.chat_id, material_id: $('pick: pg load material').item.json.material_id } }];"""

pick_normalize = {
    "parameters": {"jsCode": PICK_NORMALIZE_JS},
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [-200, 800],
    "id": new_id(),
    "name": "pick: normalize claim"
}

# IF claimed?
pick_claimed_if = {
    "parameters": {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{
                "id": "c-claimed",
                "leftValue": "={{ $json.claimed }}",
                "rightValue": True,
                "operator": {"type": "boolean", "operation": "true", "singleValue": True}
            }],
            "combinator": "and"
        },
        "options": {}
    },
    "type": "n8n-nodes-base.if",
    "typeVersion": 2,
    "position": [0, 800],
    "id": new_id(),
    "name": "pick: claimed?"
}

# pg INSERT quiz from pool entry (fast path)
PICK_INSERT_FROM_POOL_SQL = (
    "INSERT INTO app.quizzes (material_id, chat_id, questions, started_at)\n"
    "VALUES (\n"
    "  {{ $json.material_id }},\n"
    "  {{ $json.chat_id }},\n"
    "  '{{ JSON.stringify($json.questions).replace(/'/g, \"''\") }}'::jsonb,\n"
    "  now()\n"
    ")\n"
    "RETURNING id, material_id, chat_id, questions;"
)
pick_insert_from_pool = {
    "parameters": {"operation": "executeQuery", "query": PICK_INSERT_FROM_POOL_SQL, "options": {}},
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [200, 700],
    "id": new_id(),
    "name": "pick: pg INSERT quiz from pool",
    "credentials": PG_CREDS
}

# After send poll completes -> fire pool refill webhook
PICK_REFILL_BODY = (
    "={{ JSON.stringify({"
    " material_id: $('pick: pg load material').item.json.material_id,"
    " lang: $('lang: pg load pick').item.json.lang || 'en'"
    " }) }}"
)
pick_refill = {
    "parameters": {
        "method": "POST",
        "url": "=https://seniorprepcoach.ngrok.dev/webhook/pool-refill",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": PICK_REFILL_BODY,
        "options": {"timeout": 5000}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [2200, 700],
    "id": new_id(),
    "name": "pick: trigger pool refill"
}

fast_path_nodes = [pick_claim, pick_normalize, pick_claimed_if, pick_insert_from_pool, pick_refill]
nodes.extend(fast_path_nodes)
sys.stderr.write(f"Added {len(fast_path_nodes)} fast-path nodes\n")

# ============================================================
# /learn initial pool fill trigger (fire-and-forget after material insert)
# ============================================================
LEARN_REFILL_BODY = (
    "={{ JSON.stringify({"
    " material_id: $json.id,"
    " lang: $('lang: pg load /learn').item.json.lang || 'en'"
    " }) }}"
)
learn_refill = {
    "parameters": {
        "method": "POST",
        "url": "=https://seniorprepcoach.ngrok.dev/webhook/pool-refill",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": LEARN_REFILL_BODY,
        "options": {"timeout": 5000}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [1300, -500],
    "id": new_id(),
    "name": "/learn: trigger initial pool fill"
}
nodes.append(learn_refill)
sys.stderr.write("Added /learn pool trigger\n")

# ============================================================
# Rewire connections
# ============================================================

# 1. Pool refill chain
connections['pool: webhook /pool-refill'] = {
    "main": [[{"node": "pool: respond OK", "type": "main", "index": 0}]]
}
connections['pool: respond OK'] = {
    "main": [[{"node": "pool: pg count", "type": "main", "index": 0}]]
}
connections['pool: pg count'] = {
    "main": [[{"node": "pool: needs fill?", "type": "main", "index": 0}]]
}
connections['pool: needs fill?'] = {
    "main": [
        [{"node": "pool: pg load material", "type": "main", "index": 0}],  # TRUE -> generate
        []  # FALSE -> end
    ]
}
connections['pool: pg load material'] = {
    "main": [[{"node": "pool: pg load prior stems", "type": "main", "index": 0}]]
}
connections['pool: pg load prior stems'] = {
    "main": [[{"node": "pool: build examiner body", "type": "main", "index": 0}]]
}
connections['pool: build examiner body'] = {
    "main": [[{"node": "pool: Examiner (Sonnet)", "type": "main", "index": 0}]]
}
connections['pool: Examiner (Sonnet)'] = {
    "main": [[{"node": "pool: parse Examiner JSON", "type": "main", "index": 0}]]
}
connections['pool: parse Examiner JSON'] = {
    "main": [[{"node": "pool: pg INSERT pool entry", "type": "main", "index": 0}]]
}
connections['pool: pg INSERT pool entry'] = {
    "main": [[{"node": "pool: self-fire next", "type": "main", "index": 0}]]
}
sys.stderr.write("Wired pool refill chain\n")

# 2. Pick chain rewire — splice fast/slow path between lang load and ack
# Old: lang: pg load pick -> pick: build ack text -> send ack -> build examiner body -> Examiner -> parse -> pg INSERT quiz -> build poll body -> ...
# New: lang: pg load pick -> pick: pg claim from pool -> normalize -> claimed?
#         TRUE  -> pick: pg INSERT quiz from pool -> pick: build poll body (existing)
#         FALSE -> pick: build ack text -> send ack -> build examiner body -> Examiner -> parse -> pg INSERT quiz -> build poll body
connections['lang: pg load pick'] = {
    "main": [[{"node": "pick: pg claim from pool", "type": "main", "index": 0}]]
}
connections['pick: pg claim from pool'] = {
    "main": [[{"node": "pick: normalize claim", "type": "main", "index": 0}]]
}
connections['pick: normalize claim'] = {
    "main": [[{"node": "pick: claimed?", "type": "main", "index": 0}]]
}
connections['pick: claimed?'] = {
    "main": [
        [{"node": "pick: pg INSERT quiz from pool", "type": "main", "index": 0}],  # TRUE: fast
        [{"node": "pick: build ack text", "type": "main", "index": 0}]              # FALSE: slow
    ]
}
connections['pick: pg INSERT quiz from pool'] = {
    "main": [[{"node": "pick: build poll body", "type": "main", "index": 0}]]
}
# Slow path: pick: build ack text already wired to send ack -> build examiner body etc.
# We need to ensure that chain still works. Patch 20 left it as:
#   pick: build ack text -> pick: send ack -> pick: build examiner body -> ...
# But the connection after send ack went to "pick: build examiner body". Re-check.

# After patch 20, lang: pg load pick -> pick: build ack text -> send ack -> build examiner body
# Now we need send ack -> build examiner body to still work (slow path unchanged from there)
# The connections for pick: build ack text and pick: send ack from patch 20 should still be valid.

# Add pick: pg INSERT quiz -> pick: build poll body (was already there)
# Add pick: pg INSERT quiz_polls -> pick: trigger pool refill
existing_quiz_polls = connections.get('pick: pg INSERT quiz_polls', {})
if existing_quiz_polls:
    # Was terminal; now add refill trigger
    connections['pick: pg INSERT quiz_polls'] = {
        "main": [[{"node": "pick: trigger pool refill", "type": "main", "index": 0}]]
    }
    sys.stderr.write("Wired pick: pg INSERT quiz_polls -> pick: trigger pool refill\n")

# Send ack -> build examiner body (verify still wired)
# This should still be from patch 20. Ensure:
connections['pick: send ack'] = {
    "main": [[{"node": "pick: build examiner body", "type": "main", "index": 0}]]
}

# 3. /learn: pg INSERT material -> existing path + new pool trigger fan-out
learn_pg = connections.get('/learn: pg INSERT material', {})
existing_main = learn_pg.get('main', [[]])
if existing_main and existing_main[0]:
    # Append pool trigger as parallel target
    has_pool_trigger = any(t.get('node') == '/learn: trigger initial pool fill' for t in existing_main[0])
    if not has_pool_trigger:
        existing_main[0].append({"node": "/learn: trigger initial pool fill", "type": "main", "index": 0})
        learn_pg['main'] = existing_main
        sys.stderr.write("Wired /learn: pg INSERT material -> + /learn: trigger initial pool fill\n")

# Save
with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write(f"\nTotal nodes: {len(nodes)}\n")
