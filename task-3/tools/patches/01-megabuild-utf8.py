# -*- coding: utf-8 -*-
import json
import sys

# Read existing nodes JSON (UTF-8 from file)
with open('/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# ============================================================
# CLEAN replacement Code-node bodies (proper UTF-8 emoji)
# ============================================================

FORMAT_SUMMARY_JS = """const row = $input.first().json;
const materialId = row.id;
const chatId = row.chat_id;
const title = row.title || 'Untitled';
const summary = row.summary_json;

function esc(s) { return String(s == null ? '' : s).replace(/([_*`\\[])/g, '\\\\$1'); }

const diffEmoji = { beginner: '\\u{1F7E2}', intermediate: '\\u{1F7E1}', advanced: '\\u{1F534}' }[summary.difficulty] || '\\u26AA\\uFE0F';

const keyPointsBlock = summary.key_points.map((p, i) => `${i + 1}. ${esc(p)}`).join('\\n');
const conceptsBlock = summary.main_concepts.map((c) => `\\`${esc(c)}\\``).join(' \\u00B7 ');
const interviewBlock = summary.interview_angle ? `\\n\\u{1F4A1} *Interview angle:* _${esc(summary.interview_angle)}_` : '';

const text = `\\u{1F4DA} *${esc(title)}*\\n${diffEmoji} _${esc(summary.difficulty)}_\\n\\n*Key points:*\\n${keyPointsBlock}\\n\\n*Concepts:* ${conceptsBlock}${interviewBlock}\\n\\nTap below to test yourself with 5 interview-style questions.`;

const reply_markup = {
  inline_keyboard: [[{ text: '\\u{1F3AF} Take quiz now', callback_data: `pick:${materialId}` }]]
};

const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown', reply_markup });
return [{ json: { chat_id: chatId, text, reply_markup, body_json } }];"""

TOPIC_KEYBOARD_JS = """const chatId = $('Telegram Trigger1').item.json.message.chat.id;
const rows = $input.all().map(i => i.json);

let text, reply_markup;
if (!rows || rows.length === 0 || !rows[0].id) {
  text = '\\u{1F4ED} *No saved materials yet.*\\n\\nSend `/learn <url>` first.';
  reply_markup = undefined;
} else {
  const diffEmoji = { beginner: '\\u{1F7E2}', intermediate: '\\u{1F7E1}', advanced: '\\u{1F534}' };
  const inline_keyboard = rows.map((r) => [{
    text: `${diffEmoji[r.difficulty] || '\\u26AA\\uFE0F'} ${(r.title || 'Untitled').slice(0, 60)}`,
    callback_data: `pick:${r.id}`
  }]);
  text = `\\u{1F4DA} *Pick a topic to quiz on:*\\n\\nYou have ${rows.length} saved material${rows.length === 1 ? '' : 's'}.`;
  reply_markup = { inline_keyboard };
}

const payload = { chat_id: chatId, text, parse_mode: 'Markdown' };
if (reply_markup) payload.reply_markup = reply_markup;
const body_json = JSON.stringify(payload);
return [{ json: { chat_id: chatId, body_json } }];"""

FORMAT_Q1_JS = """const row = $input.first().json;
const quizId = row.id;
const chatId = row.chat_id;
const questions = (row.questions && row.questions.questions) || row.questions;
const q = questions[0];

function esc(s) { return String(s == null ? '' : s).replace(/([_*`\\[])/g, '\\\\$1'); }

const text = `\\u{1F3AF} *Question 1 of 5*\\n\\n${esc(q.question)}\\n\\n*A)* ${esc(q.options.A)}\\n*B)* ${esc(q.options.B)}\\n*C)* ${esc(q.options.C)}\\n*D)* ${esc(q.options.D)}`;

const reply_markup = {
  inline_keyboard: [
    [
      { text: 'A', callback_data: `ans:${quizId}:${q.id}:A` },
      { text: 'B', callback_data: `ans:${quizId}:${q.id}:B` },
    ],
    [
      { text: 'C', callback_data: `ans:${quizId}:${q.id}:C` },
      { text: 'D', callback_data: `ans:${quizId}:${q.id}:D` },
    ],
  ]
};

const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown', reply_markup });
return [{ json: { chat_id: chatId, body_json } }];"""

FORMAT_NEXT_Q_JS = """const v = $('ans: validate').item.json;
const questions = v.questions;
const nextQ = questions[v.next_q_idx];
const chatId = v.chat_id;
const quizId = v.quiz_id;
const qNum = v.next_q_idx + 1;

function esc(s) { return String(s == null ? '' : s).replace(/([_*`\\[])/g, '\\\\$1'); }

const prevMark = v.correct ? '\\u2705 correct' : `\\u274C wrong (was *${v.correct_answer}*)`;
const text = `${prevMark}\\n\\n\\u{1F3AF} *Question ${qNum} of 5*\\n\\n${esc(nextQ.question)}\\n\\n*A)* ${esc(nextQ.options.A)}\\n*B)* ${esc(nextQ.options.B)}\\n*C)* ${esc(nextQ.options.C)}\\n*D)* ${esc(nextQ.options.D)}`;

const reply_markup = {
  inline_keyboard: [
    [
      { text: 'A', callback_data: `ans:${quizId}:${nextQ.id}:A` },
      { text: 'B', callback_data: `ans:${quizId}:${nextQ.id}:B` },
    ],
    [
      { text: 'C', callback_data: `ans:${quizId}:${nextQ.id}:C` },
      { text: 'D', callback_data: `ans:${quizId}:${nextQ.id}:D` },
    ],
  ]
};

const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown', reply_markup });
return [{ json: { chat_id: chatId, body_json } }];"""

FORMAT_RESULTS_JS = """const answers = $input.all().map(i => i.json);
const chatId = $('ans: validate').item.json.chat_id;
const quizId = $('ans: validate').item.json.quiz_id;

const raw = answers[0]?.questions;
const questions = (raw && raw.questions) || raw;

const correctCount = answers.filter(a => a.correct).length;
const total = answers.length;
const pct = Math.round(100 * correctCount / total);

let badge;
if (pct >= 80) badge = '\\u{1F3C6}';
else if (pct >= 60) badge = '\\u2705';
else if (pct >= 40) badge = '\\u26A0\\uFE0F';
else badge = '\\u{1F53B}';

const lines = [`${badge} *Quiz complete: ${correctCount}/${total} (${pct}%)*`, ''];

for (const a of answers) {
  const q = questions.find(qq => qq.id === a.question_id);
  const mark = a.correct ? '\\u2705' : '\\u274C';
  const userOpt = q?.options?.[a.user_answer] || '';
  const correctLetter = q?.correctAnswer || '?';
  const correctOpt = q?.options?.[correctLetter] || '';

  lines.push(`${mark} *${a.question_id}* \\u2014 you picked _${a.user_answer}_: ${userOpt}`);
  if (!a.correct) {
    lines.push(`     \\u2713 Correct: *${correctLetter}* \\u2014 ${correctOpt}`);
    if (q?.explanation) lines.push(`     \\u{1F4A1} _${q.explanation}_`);
  }
  lines.push('');
}

lines.push(pct >= 80
  ? `_Strong recall \\u2014 this material is well-internalised._`
  : pct >= 60
    ? `_Solid baseline \\u2014 re-skim the points you missed._`
    : `_Worth a deeper re-read \\u2014 consider running /quiz on this topic again later._`);

lines.push('');
lines.push('Use `/quiz` to test another topic, or `/learn <url>` to add a new one.');

const text = lines.join('\\n');
const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
return [{ json: { chat_id: chatId, text, body_json } }];"""

STATS_FORMAT_JS = """const chatId = $('Telegram Trigger1').item.json.message.chat.id;
const row = $input.first().json;

if (!row || row.materials_count === undefined || row.materials_count === null) {
  const text = '\\u{1F4CA} *No learning history yet.*\\n\\nSend `/learn <url>` to add your first material \\u2014 once you take a quiz, your stats will show up here.';
  const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
  return [{ json: { chat_id: chatId, text, body_json } }];
}

function bar(n, total = 10) {
  const filled = Math.min(total, Math.max(0, Math.round((n / 100) * total)));
  return '\\u2588'.repeat(filled) + '\\u2591'.repeat(total - filled);
}

const score = Number(row.avg_score_pct) || 0;
const lastQuiz = row.last_quiz_at ? new Date(row.last_quiz_at).toISOString().split('T')[0] : 'never';

const lines = [
  '\\u{1F4CA} *Your learning dashboard*',
  '',
  `\\u{1F4DA} *Materials saved:* ${row.materials_count}`,
  `   \\u{1F7E2} beginner: ${row.beginner_materials || 0}`,
  `   \\u{1F7E1} intermediate: ${row.intermediate_materials || 0}`,
  `   \\u{1F534} advanced: ${row.advanced_materials || 0}`,
  '',
  `\\u{1F3AF} *Quizzes taken:* ${row.quizzes_taken || 0}`,
  `\\u{1F4C8} *Average score:* ${score}%`,
  `      \\`${bar(score)}\\``,
  `\\u{1F552} *Last quiz:* ${lastQuiz}`,
  '',
  '_Tip: re-quiz a topic after a few days to test retention._',
];

const text = lines.join('\\n');
const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
return [{ json: { chat_id: chatId, text, body_json } }];"""

# Examiner parse - add randomization to spread correctAnswer across A/B/C/D
PARSE_EXAMINER_JS = """const mat = $('pick: pg load material').item.json;
const response = $input.first().json;
const rawText = response?.content?.[0]?.text || '';

let parsed;
try {
  const cleaned = rawText.replace(/^```(?:json)?\\s*/i, '').replace(/\\s*```\\s*$/i, '').trim();
  parsed = JSON.parse(cleaned);
} catch (err) {
  throw new Error('Examiner returned unparseable JSON: ' + rawText.slice(0, 300));
}

if (!Array.isArray(parsed.questions) || parsed.questions.length !== 5) {
  throw new Error('Examiner did not return 5 questions, got: ' + (parsed.questions || []).length);
}

// Validate each question + RANDOMIZE option order so correctAnswer isn't always A
const letters = ['A','B','C','D'];
for (let i = 0; i < 5; i++) {
  const q = parsed.questions[i];
  if (!q.id) q.id = `Q${i + 1}`;
  if (!q.options || !q.options.A || !q.options.B || !q.options.C || !q.options.D) {
    throw new Error(`Q${i + 1} missing options A-D`);
  }
  q.correctAnswer = String(q.correctAnswer || '').toUpperCase();
  if (!letters.includes(q.correctAnswer)) {
    throw new Error(`Q${i + 1} has invalid correctAnswer: ${q.correctAnswer}`);
  }
  q.explanation = q.explanation || '';

  // Shuffle option order to spread correctAnswer across A/B/C/D
  const correctText = q.options[q.correctAnswer];
  const wrongTexts = letters.filter(l => l !== q.correctAnswer).map(l => q.options[l]);
  // Fisher-Yates shuffle wrongTexts
  for (let j = wrongTexts.length - 1; j > 0; j--) {
    const k = Math.floor(Math.random() * (j + 1));
    [wrongTexts[j], wrongTexts[k]] = [wrongTexts[k], wrongTexts[j]];
  }
  // Pick random target slot for the correct answer
  const targetLetter = letters[Math.floor(Math.random() * 4)];
  const newOptions = {};
  let wi = 0;
  for (const L of letters) {
    if (L === targetLetter) newOptions[L] = correctText;
    else newOptions[L] = wrongTexts[wi++];
  }
  q.options = newOptions;
  q.correctAnswer = targetLetter;
}

return [{ json: { material_id: mat.material_id, chat_id: mat.chat_id, questions: parsed.questions } }];"""

# Ack node uses HTTP Request type, jsonBody field has emoji
ACK_BODY = '={ "chat_id": {{ $json.chat_id }}, "text": "\\u{1F50D} Reading the article and asking the Teacher (Claude Opus 4.7) to distill it at senior level... typically 30-60 seconds." }'

# Apply patches
code_patches = {
    '/learn: format summary': FORMAT_SUMMARY_JS,
    '/quiz: build topic keyboard': TOPIC_KEYBOARD_JS,
    'pick: format Q1': FORMAT_Q1_JS,
    'ans: format next Q': FORMAT_NEXT_Q_JS,
    'ans: format results': FORMAT_RESULTS_JS,
    '/stats: format': STATS_FORMAT_JS,
    'pick: parse Examiner JSON': PARSE_EXAMINER_JS,
}

count = 0
for n in nodes:
    name = n.get('name', '')
    if name in code_patches:
        n['parameters']['jsCode'] = code_patches[name]
        sys.stderr.write(f"Patched (UTF-8 clean): {name}\n")
        count += 1
    elif name == '/learn: send ack (loading)':
        n['parameters']['jsonBody'] = ACK_BODY
        sys.stderr.write(f"Patched ack body: {name}\n")
        count += 1

sys.stderr.write(f"\nTotal: {count}\n")

with open('/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
sys.stderr.write("Wrote /tmp/db_nodes_fixed.json\n")
