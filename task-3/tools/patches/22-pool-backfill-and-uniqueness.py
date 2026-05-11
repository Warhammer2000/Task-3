"""Patch 22: backfill pool for existing materials + tighter uniqueness guarantee.

Three changes:

1. Stronger uniqueness directive in pool: build examiner body — explicit
   5-rule instruction list + permission for at most 1 overlap (escape hatch
   when material is exhausted).

2. New Code node "pool: similarity check" between parse and pg INSERT —
   computes Jaccard-bigram similarity of each new question vs all prior
   stems. If any new Q has similarity > 0.55 with any prior, the entry is
   STILL inserted but a console warning is logged. (Hard rejection would
   risk infinite-loop generation when material gets exhausted; logging
   gives ops visibility without breaking the user flow.)

3. New "pool backfill" trigger — fired on first n8n startup via the
   pool-refill webhook for every (material_id, lang) combo with 0 pool
   entries. This is invoked manually (curl loop in tools/) since adding
   a startup trigger to n8n is fragile.
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# ============================================================
# 1. Stronger uniqueness directive in pool: build examiner body
# ============================================================
POOL_BUILD_BODY_JS = r"""// Build Anthropic Examiner request body for pool quiz generation
const mat = $('pool: pg load material').item.json;
const lang = ($('pool: webhook /pool-refill').item.json.body.lang || 'en').replace(/[^a-z]/g,'') || 'en';
const priorStems = $('pool: pg load prior stems').item.json.prior_stems || '';
const priorCount = priorStems ? priorStems.split('\n').length : 0;

const langDirective = lang === 'ru'
  ? '\n\nAll output strings (question, options A/B/C/D, explanation) must be in Russian. Answer letters stay A/B/C/D.'
  : '';

const uniqueDirective = priorStems
  ? `\n\nUNIQUENESS REQUIREMENT (CRITICAL): ${priorCount} prior questions already exist for this material:

---
${priorStems}
---

Your 5 NEW questions MUST satisfy ALL of these rules:
1. Test DIFFERENT concepts/angles than the prior questions above.
2. NOT a paraphrase or restatement of any prior question (even with synonyms).
3. Cover material observations the prior questions missed (look for unexplored sub-topics).
4. Use DIFFERENT framing/scenarios (vary team sizes, deployment contexts, scaling tiers, failure modes).
5. Probe DIFFERENT sections of the material content (not the same paragraph that prior questions covered).

If after careful review you genuinely cannot find 5 truly new angles (material is small or already deeply covered), you may overlap on AT MOST 1 question — but mark that question's explanation with "(rephrased)" so the operator sees it.

Self-check before output: read each of your 5 generated questions and compare against the prior list above. If you spot a near-duplicate, REPLACE it with a fresher angle.`
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
  temperature: 0.9,
  system: systemPrompt,
  messages: [{ role: 'user', content: userContent }]
});

return [{ json: { ...mat, lang, examiner_body, generation_model: 'claude-sonnet-4-5', prior_count: priorCount } }];"""

for n in nodes:
    if n.get('name') == 'pool: build examiner body':
        n['parameters']['jsCode'] = POOL_BUILD_BODY_JS
        sys.stderr.write("Patched pool: build examiner body (stronger uniqueness directive)\n")

# ============================================================
# 2. Add similarity-check Code node between parse and pg INSERT
# ============================================================
import uuid

POOL_SIM_CHECK_JS = r"""// Compute Jaccard-bigram similarity of each new question vs prior stems.
// Log warnings if any new question is too similar to any prior. Does NOT block
// insertion — Sonnet 4.5 + temperature 0.9 + strong directive usually keeps
// similarity below threshold; logging gives ops visibility.

function bigrams(s) {
  const norm = String(s || '').toLowerCase().replace(/[^a-zа-яё0-9 ]/gi, ' ').replace(/\s+/g, ' ').trim();
  const bgs = new Set();
  for (let i = 0; i < norm.length - 1; i++) {
    bgs.add(norm.slice(i, i + 2));
  }
  return bgs;
}

function jaccard(a, b) {
  if (!a.size || !b.size) return 0;
  let inter = 0;
  for (const x of a) if (b.has(x)) inter++;
  return inter / (a.size + b.size - inter);
}

const item = $input.first().json;
const newQs = item.questions?.questions || [];
const priorStems = ($('pool: pg load prior stems').item.json.prior_stems || '').split('\n').filter(s => s.trim());

const SIMILARITY_THRESHOLD = 0.55;
const warnings = [];

const priorBigrams = priorStems.map(s => ({ stem: s, bgs: bigrams(s) }));

for (const q of newQs) {
  const newBgs = bigrams(q.question);
  let maxSim = 0;
  let maxStem = '';
  for (const p of priorBigrams) {
    const sim = jaccard(newBgs, p.bgs);
    if (sim > maxSim) {
      maxSim = sim;
      maxStem = p.stem;
    }
  }
  if (maxSim > SIMILARITY_THRESHOLD) {
    warnings.push(`${q.id}: similarity=${maxSim.toFixed(2)} vs "${maxStem.slice(0, 60)}..."`);
  }
}

if (warnings.length) {
  console.log(`[pool similarity warn] material=${item.material_id} lang=${item.lang} prior=${priorStems.length}: ${warnings.length} of 5 questions exceed ${SIMILARITY_THRESHOLD} threshold`);
  for (const w of warnings) console.log('  ' + w);
}

return [{ json: { ...item, similarity_warnings: warnings.length } }];"""

sim_check_node = {
    "parameters": {"jsCode": POOL_SIM_CHECK_JS},
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [300, 1500],
    "id": str(uuid.uuid4()),
    "name": "pool: similarity check"
}

# Add only if not present
if not any(n.get('name') == 'pool: similarity check' for n in nodes):
    nodes.append(sim_check_node)
    sys.stderr.write("Added pool: similarity check node\n")

# Rewire: pool: parse Examiner JSON -> pool: similarity check -> pool: pg INSERT pool entry
connections['pool: parse Examiner JSON'] = {
    "main": [[{"node": "pool: similarity check", "type": "main", "index": 0}]]
}
connections['pool: similarity check'] = {
    "main": [[{"node": "pool: pg INSERT pool entry", "type": "main", "index": 0}]]
}
sys.stderr.write("Wired similarity check between parse and INSERT\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
