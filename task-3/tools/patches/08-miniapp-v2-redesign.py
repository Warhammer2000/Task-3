"""Mini App v2 — stunning redesign + effects mapping fix."""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# Updated effect mapping (drop 💩, use proven IDs)
FORMAT_RESULTS_JS = r"""const answers = $input.all().map(i => i.json);

const src = $('poll_ans: validate').isExecuted
  ? $('poll_ans: validate').item.json
  : $('ans: validate').item.json;
const chatId = src.chat_id;

const raw = answers[0]?.questions;
const questions = (raw && raw.questions) || raw;

const correctCount = answers.filter(a => a.correct).length;
const total = answers.length;
const pct = Math.round(100 * correctCount / total);

let badge, effectId;
if (pct >= 80)      { badge = '\u{1F3C6}'; effectId = '5104841245755180586'; }  // fire
else if (pct >= 60) { badge = '✨';   effectId = '5046509860389126442'; }  // confetti
else if (pct >= 40) { badge = '\u{1F4A1}'; effectId = '5107584321108051014'; }  // thumbs up
else                { badge = '\u{1F94A}'; effectId = '5104858069142078462'; }  // thumbs down ("keep punching")

function esc(s) { return String(s).replace(/([_*`\[\]])/g, '\\$1'); }

const lines = [`${badge} *Quiz complete: ${correctCount}/${total} (${pct}%)*`, ''];

for (const a of answers) {
  const q = questions.find(qq => qq.id === a.question_id);
  const mark = a.correct ? '✅' : '❌';
  const userOpt = esc(q?.options?.[a.user_answer] || '');
  const correctLetter = q?.correctAnswer || '?';
  const correctOpt = esc(q?.options?.[correctLetter] || '');

  lines.push(`${mark} *${a.question_id}* — you picked _${a.user_answer}_: ${userOpt}`);
  if (!a.correct) {
    lines.push(`     ✓ Correct: *${correctLetter}* — ${correctOpt}`);
    if (q?.explanation) lines.push(`     \u{1F4A1} _${esc(q.explanation)}_`);
  }
  lines.push('');
}

lines.push(pct >= 80
  ? `_Strong recall — this material is well-internalised._`
  : pct >= 60
    ? `_Solid baseline — re-skim the points you missed._`
    : pct >= 40
      ? `_Halfway there — re-read the missed sections and run /quiz again._`
      : `_Worth a deep re-read — try the material once more and re-quiz tomorrow._`);

lines.push('');
lines.push('Open `/stats` for your full dashboard, or `/learn <url>` to add another topic.');

const text = lines.join('\n');
const bodyObj = { chat_id: chatId, text, parse_mode: 'Markdown' };
if (effectId) bodyObj.message_effect_id = effectId;
const body_json = JSON.stringify(bodyObj);
return [{ json: { chat_id: chatId, text, body_json } }];"""

# Updated mini-app SQL with activity
MINIAPP_PG_SQL = (
    "SELECT \n"
    "  COALESCE(v.materials_count, 0) AS materials_count,\n"
    "  COALESCE(v.quizzes_taken, 0) AS quizzes_taken,\n"
    "  COALESCE(v.avg_score_pct, 0) AS avg_score_pct,\n"
    "  COALESCE(v.beginner_materials, 0) AS beginner_materials,\n"
    "  COALESCE(v.intermediate_materials, 0) AS intermediate_materials,\n"
    "  COALESCE(v.advanced_materials, 0) AS advanced_materials,\n"
    "  v.last_quiz_at,\n"
    "  (SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (\n"
    "    SELECT id, title, difficulty,\n"
    "           to_char(added_at AT TIME ZONE 'UTC','YYYY-MM-DD') AS added_at,\n"
    "           (SELECT MAX(score_pct) FROM app.quizzes q WHERE q.material_id = m.id AND q.finished_at IS NOT NULL) AS best_score\n"
    "    FROM app.learning_materials m\n"
    "    WHERE m.chat_id = {{ Number($json.query.chat_id) }}\n"
    "    ORDER BY added_at DESC LIMIT 20\n"
    "  ) t) AS materials,\n"
    "  (SELECT COALESCE(json_agg(row_to_json(t) ORDER BY t.finished_at), '[]'::json) FROM (\n"
    "    SELECT q.id, q.score_pct,\n"
    "           to_char(q.finished_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI') AS finished_at,\n"
    "           m.title, m.difficulty\n"
    "    FROM app.quizzes q JOIN app.learning_materials m ON m.id = q.material_id\n"
    "    WHERE q.chat_id = {{ Number($json.query.chat_id) }} AND q.finished_at IS NOT NULL\n"
    "    ORDER BY q.finished_at DESC LIMIT 20\n"
    "  ) t) AS quizzes,\n"
    "  (SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (\n"
    "    SELECT to_char(date_trunc('day', finished_at AT TIME ZONE 'UTC'),'YYYY-MM-DD') AS day,\n"
    "           COUNT(*)::INT AS cnt,\n"
    "           ROUND(AVG(score_pct))::INT AS avg_pct\n"
    "    FROM app.quizzes\n"
    "    WHERE chat_id = {{ Number($json.query.chat_id) }}\n"
    "      AND finished_at IS NOT NULL\n"
    "      AND finished_at > now() - interval '28 days'\n"
    "    GROUP BY 1\n"
    "  ) t) AS activity,\n"
    "  (SELECT COUNT(*) FILTER (WHERE score_pct = 100)::INT FROM app.quizzes WHERE chat_id = {{ Number($json.query.chat_id) }}) AS perfect_quizzes,\n"
    "  (SELECT MAX(score_pct) FROM app.quizzes WHERE chat_id = {{ Number($json.query.chat_id) }} AND finished_at IS NOT NULL) AS best_score\n"
    "FROM (SELECT 1) dummy\n"
    "LEFT JOIN app.v_user_stats v ON v.chat_id = {{ Number($json.query.chat_id) }};"
)

# Beautiful HTML
MINIAPP_RENDER_JS = r"""// Render premium Mini App HTML
const row = $input.first().json || {};
const materials = row.materials || [];
const quizzes = row.quizzes || [];
const activity = row.activity || [];
const total = row.materials_count || 0;
const taken = row.quizzes_taken || 0;
const avg = Math.round(row.avg_score_pct || 0);
const beg = row.beginner_materials || 0;
const inter = row.intermediate_materials || 0;
const adv = row.advanced_materials || 0;
const perfectQ = row.perfect_quizzes || 0;
const bestScore = row.best_score || 0;
const lastAt = row.last_quiz_at ? new Date(row.last_quiz_at).toISOString().split('T')[0] : null;

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

// Achievements
const achievements = [
  { icon: '🌱', title: 'First spark',     sub: 'Saved your first material', unlocked: total >= 1 },
  { icon: '📚', title: 'Library starter', sub: '5+ materials saved',         unlocked: total >= 5 },
  { icon: '🎯', title: 'Initiate',        sub: 'Took your first quiz',       unlocked: taken >= 1 },
  { icon: '🔥', title: 'On a roll',       sub: 'Took 5+ quizzes',            unlocked: taken >= 5 },
  { icon: '💎', title: 'Perfectionist',   sub: 'Hit 100% on a quiz',         unlocked: perfectQ >= 1 },
  { icon: '🏆', title: 'Top form',        sub: 'Personal best ≥ 80%',        unlocked: bestScore >= 80 },
  { icon: '🦉', title: 'Triple stack',    sub: 'All 3 difficulty levels',    unlocked: beg > 0 && inter > 0 && adv > 0 },
];

const badges = achievements.map(a => `
  <div class="badge ${a.unlocked ? 'on' : 'off'}">
    <div class="badge-icon">${a.icon}</div>
    <div class="badge-title">${esc(a.title)}</div>
    <div class="badge-sub">${esc(a.sub)}</div>
  </div>`).join('');

// Library rows
const matRows = materials.map(m => {
  const score = m.best_score;
  const scoreBlock = score != null
    ? `<div class="score-mini"><div class="sm-track"><div class="sm-fill" style="width:${score}%"></div></div><span class="sm-val">${score}%</span></div>`
    : `<div class="lib-meta dim">never quizzed</div>`;
  return `
    <div class="lib-row">
      <div class="lib-icon ${esc(m.difficulty)}">${m.difficulty === 'advanced' ? '🔴' : m.difficulty === 'intermediate' ? '🟡' : '🟢'}</div>
      <div class="lib-body">
        <div class="lib-title">${esc(m.title)}</div>
        ${scoreBlock}
      </div>
    </div>`;
}).join('');

// Heatmap: last 28 days
const activityMap = {};
activity.forEach(a => { activityMap[a.day] = a; });
const heatCells = [];
const today = new Date();
today.setUTCHours(0,0,0,0);
for (let i = 27; i >= 0; i--) {
  const d = new Date(today);
  d.setUTCDate(d.getUTCDate() - i);
  const key = d.toISOString().split('T')[0];
  const day = activityMap[key];
  let level = 0;
  if (day) {
    if (day.cnt >= 3 || day.avg_pct >= 80) level = 4;
    else if (day.cnt >= 2 || day.avg_pct >= 60) level = 3;
    else if (day.avg_pct >= 40) level = 2;
    else level = 1;
  }
  const title = day ? `${key}: ${day.cnt} quiz${day.cnt > 1 ? 'zes' : ''}, ${day.avg_pct}% avg` : key;
  heatCells.push(`<div class="cell l${level}" title="${title}"></div>`);
}

// Quiz history items
const quizRows = quizzes.slice().reverse().slice(0, 8).map(q => {
  const cls = q.score_pct >= 80 ? 'good' : q.score_pct >= 60 ? 'mid' : q.score_pct >= 40 ? 'low' : 'bad';
  return `
    <div class="quiz-row">
      <div class="quiz-title">${esc(q.title)}</div>
      <div class="quiz-meta">${esc(q.finished_at)}</div>
      <div class="score-bar">
        <div class="sb-track"><div class="sb-fill ${cls}" data-fill="${q.score_pct}" style="width:0%"></div></div>
        <span class="sb-val">${q.score_pct}%</span>
      </div>
    </div>`;
}).join('');

const lastBlock = lastAt ? `Last quiz · ${lastAt}` : 'Take a quiz to see your stats';

const chartData = {
  diff: [beg, inter, adv],
  scores: quizzes.map(q => q.score_pct),
  labels: quizzes.map((q, i) => `#${i+1}`),
  titles: quizzes.map(q => q.title),
};

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Senior Backend Coach — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {
    --tg-bg: var(--tg-theme-bg-color, #0f1115);
    --tg-fg: var(--tg-theme-text-color, #ECEFF4);
    --tg-hint: var(--tg-theme-hint-color, #8a93a0);
    --tg-button: var(--tg-theme-button-color, #5b8aff);
    --tg-button-text: var(--tg-theme-button-text-color, #ffffff);
    --tg-secondary-bg: var(--tg-theme-secondary-bg-color, #1c1f26);
    --accent: #5b8aff;
    --accent-2: #b07cff;
    --accent-3: #ff7eb6;
    --success: #34c759;
    --warn: #ffcc00;
    --danger: #ff453a;
    --card: rgba(255,255,255,0.04);
    --card-h: rgba(255,255,255,0.07);
    --border: rgba(255,255,255,0.08);
    --border-s: rgba(255,255,255,0.14);
    --radius: 16px;
    --radius-sm: 10px;
  }
  *, *::before, *::after { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--tg-bg);
    color: var(--tg-fg);
    font: 14.5px/1.5 -apple-system, BlinkMacSystemFont, "Inter", "SF Pro Text", "Segoe UI", Roboto, sans-serif;
    padding-bottom: 80px;
    overscroll-behavior: contain;
    letter-spacing: -0.011em;
    min-height: 100vh;
  }

  /* HERO */
  .hero {
    position: relative;
    padding: 28px 18px 78px;
    overflow: hidden;
    background:
      radial-gradient(ellipse 80% 60% at 50% -10%, rgba(91,138,255,0.30) 0%, transparent 60%),
      radial-gradient(ellipse 60% 50% at 110% 20%, rgba(176,124,255,0.20) 0%, transparent 60%),
      radial-gradient(ellipse 50% 40% at -10% 50%, rgba(255,126,182,0.10) 0%, transparent 60%);
  }
  .hero::before, .hero::after {
    content: '';
    position: absolute;
    width: 320px; height: 320px;
    border-radius: 50%;
    filter: blur(50px);
    opacity: 0.6;
    pointer-events: none;
  }
  .hero::before {
    top: -160px; right: -80px;
    background: radial-gradient(circle, rgba(91,138,255,0.45) 0%, transparent 70%);
    animation: floatA 14s ease-in-out infinite;
  }
  .hero::after {
    bottom: -100px; left: -100px;
    background: radial-gradient(circle, rgba(176,124,255,0.35) 0%, transparent 70%);
    animation: floatB 18s ease-in-out infinite;
  }
  @keyframes floatA { 0%,100% { transform: translate(0,0); } 50% { transform: translate(-40px,30px); } }
  @keyframes floatB { 0%,100% { transform: translate(0,0); } 50% { transform: translate(50px,-25px); } }

  .hero-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  .hero-emoji {
    font-size: 32px;
    filter: drop-shadow(0 6px 18px rgba(91,138,255,0.5));
    animation: pulse 4s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100% { transform: scale(1); } 50% { transform: scale(1.08); } }

  h1 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.02em; }
  .sub { color: var(--tg-hint); font-size: 13px; margin-bottom: 24px; }

  .kpis {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; position: relative; z-index: 1;
  }
  .kpi {
    background: rgba(255,255,255,0.06);
    backdrop-filter: blur(20px) saturate(180%);
    -webkit-backdrop-filter: blur(20px) saturate(180%);
    border: 1px solid var(--border-s);
    border-radius: var(--radius);
    padding: 14px 10px;
    text-align: center;
    transition: transform 0.2s, background 0.2s;
  }
  .kpi:active { transform: scale(0.97); background: var(--card-h); }
  .kpi .l {
    font-size: 10.5px; color: var(--tg-hint);
    text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;
  }
  .kpi .v {
    font-size: 28px; font-weight: 800; margin-top: 4px; line-height: 1;
    background: linear-gradient(135deg, #fff, #b9c5ff);
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent; color: transparent;
  }
  .kpi.amber .v { background: linear-gradient(135deg, #fff, #ffd87a); -webkit-background-clip: text; background-clip: text; }
  .kpi.green .v { background: linear-gradient(135deg, #fff, #8af0a8); -webkit-background-clip: text; background-clip: text; }
  .kpi .suffix { font-size: 16px; opacity: 0.5; margin-left: 1px; }

  /* CONTENT */
  .content { margin-top: -52px; padding: 0 14px; position: relative; z-index: 2; }
  .card {
    background: var(--card);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    margin-bottom: 12px;
  }
  .card h2 {
    margin: 0 0 12px; font-size: 11.5px; color: var(--tg-hint);
    text-transform: uppercase; letter-spacing: 0.07em; font-weight: 600;
    display: flex; align-items: center; gap: 8px;
  }
  .card h2 .pill {
    background: var(--card-h); padding: 2px 7px; border-radius: 5px; font-size: 10px;
    letter-spacing: 0; text-transform: none; color: var(--tg-fg); opacity: 0.6; margin-left: auto;
  }

  /* ACHIEVEMENTS */
  .badges { display: flex; gap: 8px; overflow-x: auto; scroll-snap-type: x mandatory; padding-bottom: 4px; margin: 0 -16px; padding-left: 16px; padding-right: 16px; }
  .badges::-webkit-scrollbar { display: none; }
  .badge {
    flex: 0 0 100px; padding: 14px 8px; border-radius: var(--radius-sm); text-align: center;
    scroll-snap-align: start; position: relative; overflow: hidden;
  }
  .badge.on {
    background: linear-gradient(155deg, rgba(91,138,255,0.22), rgba(176,124,255,0.10));
    border: 1px solid var(--border-s);
    box-shadow: 0 4px 14px rgba(91,138,255,0.12);
  }
  .badge.off { background: var(--card); border: 1px solid var(--border); opacity: 0.42; }
  .badge.on::before {
    content: ''; position: absolute; inset: 0;
    background: linear-gradient(135deg, rgba(255,255,255,0.10), transparent 60%);
    pointer-events: none;
  }
  .badge-icon { font-size: 26px; line-height: 1; margin-bottom: 4px; filter: drop-shadow(0 2px 6px rgba(0,0,0,0.35)); }
  .badge-title { font-size: 11px; font-weight: 700; margin-bottom: 2px; }
  .badge-sub { font-size: 10px; color: var(--tg-hint); line-height: 1.25; }

  /* CHARTS */
  .charts-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
  @media (min-width: 480px) { .charts-grid { grid-template-columns: 1fr 1fr; } }
  canvas { max-width: 100%; }

  /* HEATMAP */
  .heatmap { display: grid; grid-template-columns: repeat(28, 1fr); gap: 3px; }
  .heatmap .cell {
    aspect-ratio: 1; border-radius: 2.5px; background: rgba(255,255,255,0.04);
    transition: transform 0.15s, background 0.2s;
    will-change: transform;
  }
  .heatmap .cell.l1 { background: rgba(91,138,255,0.30); }
  .heatmap .cell.l2 { background: rgba(91,138,255,0.55); }
  .heatmap .cell.l3 { background: rgba(91,138,255,0.80); }
  .heatmap .cell.l4 { background: linear-gradient(135deg, #5b8aff, #b07cff); box-shadow: 0 0 8px rgba(91,138,255,0.4); }
  .heatmap-legend { display: flex; align-items: center; gap: 4px; font-size: 10px; color: var(--tg-hint); margin-top: 8px; }
  .heatmap-legend .swatch { width: 10px; height: 10px; border-radius: 2px; }

  /* LIBRARY */
  .lib-row { display: flex; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); align-items: center; }
  .lib-row:last-child { border-bottom: 0; }
  .lib-icon {
    flex: 0 0 38px; height: 38px; border-radius: 10px;
    display: grid; place-items: center; font-size: 16px;
    background: var(--card-h);
  }
  .lib-icon.beginner { background: rgba(52,199,89,0.15); }
  .lib-icon.intermediate { background: rgba(255,204,0,0.15); }
  .lib-icon.advanced { background: rgba(255,69,58,0.15); }
  .lib-body { flex: 1; min-width: 0; }
  .lib-title { font-size: 13.5px; font-weight: 500; line-height: 1.35;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .lib-meta { font-size: 11px; color: var(--tg-hint); margin-top: 2px; }
  .lib-meta.dim { font-style: italic; opacity: 0.7; }

  /* MINI SCORE BAR (library) */
  .score-mini { display: flex; align-items: center; gap: 8px; margin-top: 5px; }
  .sm-track { flex: 1; height: 4px; background: var(--card-h); border-radius: 2px; overflow: hidden; }
  .sm-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); border-radius: 2px; }
  .sm-val { font-size: 11px; font-weight: 600; min-width: 32px; text-align: right; }

  /* QUIZ HISTORY */
  .quiz-row { padding: 12px 0; border-bottom: 1px solid var(--border); }
  .quiz-row:last-child { border-bottom: 0; }
  .quiz-title { font-size: 13.5px; font-weight: 500; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .quiz-meta { font-size: 11px; color: var(--tg-hint); margin-top: 1px; margin-bottom: 6px; }
  .score-bar { display: flex; align-items: center; gap: 10px; }
  .sb-track { flex: 1; height: 6px; background: var(--card-h); border-radius: 3px; overflow: hidden; }
  .sb-fill { height: 100%; border-radius: 3px; transition: width 1.2s cubic-bezier(0.22, 1, 0.36, 1); }
  .sb-fill.good { background: linear-gradient(90deg, #34c759, #5cd97e); }
  .sb-fill.mid  { background: linear-gradient(90deg, #ffcc00, #ffd87a); }
  .sb-fill.low  { background: linear-gradient(90deg, #ff9500, #ffbb55); }
  .sb-fill.bad  { background: linear-gradient(90deg, #ff453a, #ff7e74); }
  .sb-val { font-size: 12px; font-weight: 700; min-width: 40px; text-align: right; }

  .empty { text-align: center; color: var(--tg-hint); padding: 24px 0; font-style: italic; font-size: 13px; }

  /* Animations on mount */
  .reveal { opacity: 0; transform: translateY(8px); animation: reveal 0.5s cubic-bezier(0.22, 1, 0.36, 1) forwards; }
  @keyframes reveal { to { opacity: 1; transform: none; } }
  .reveal-1 { animation-delay: 0.05s; }
  .reveal-2 { animation-delay: 0.10s; }
  .reveal-3 { animation-delay: 0.15s; }
  .reveal-4 { animation-delay: 0.20s; }
  .reveal-5 { animation-delay: 0.25s; }
  .reveal-6 { animation-delay: 0.30s; }
</style>
</head>
<body>
  <header class="hero">
    <div class="hero-head">
      <div class="hero-emoji">📊</div>
      <h1>Your dashboard</h1>
    </div>
    <div class="sub">Senior backend prep · ${esc(lastBlock)}</div>
    <div class="kpis">
      <div class="kpi reveal reveal-1"><div class="l">Materials</div><div class="v" data-count="${total}">0</div></div>
      <div class="kpi amber reveal reveal-2"><div class="l">Quizzes</div><div class="v" data-count="${taken}">0</div></div>
      <div class="kpi green reveal reveal-3"><div class="l">Avg score</div><div class="v"><span data-count="${avg}">0</span><span class="suffix">%</span></div></div>
    </div>
  </header>

  <main class="content">

    <div class="card reveal reveal-2">
      <h2>Achievements <span class="pill">${achievements.filter(a => a.unlocked).length}/${achievements.length}</span></h2>
      <div class="badges">${badges}</div>
    </div>

    <div class="charts-grid">
      <div class="card reveal reveal-3">
        <h2>Difficulty mix</h2>
        <canvas id="diffChart" height="180"></canvas>
      </div>
      <div class="card reveal reveal-4">
        <h2>Score trend</h2>
        <canvas id="trendChart" height="180"></canvas>
      </div>
    </div>

    <div class="card reveal reveal-4">
      <h2>Activity <span class="pill">last 28 days</span></h2>
      <div class="heatmap" id="heatmap">${heatCells.join('')}</div>
      <div class="heatmap-legend">
        Less
        <div class="swatch" style="background:rgba(255,255,255,0.04)"></div>
        <div class="swatch" style="background:rgba(91,138,255,0.30)"></div>
        <div class="swatch" style="background:rgba(91,138,255,0.55)"></div>
        <div class="swatch" style="background:rgba(91,138,255,0.80)"></div>
        <div class="swatch" style="background:linear-gradient(135deg,#5b8aff,#b07cff)"></div>
        More
      </div>
    </div>

    <div class="card reveal reveal-5">
      <h2>Library <span class="pill">${materials.length}</span></h2>
      ${materials.length ? matRows : '<div class="empty">Send <code>/learn &lt;url&gt;</code> in chat to add your first material.</div>'}
    </div>

    <div class="card reveal reveal-6">
      <h2>Recent quizzes</h2>
      ${quizzes.length ? quizRows : '<div class="empty">No quizzes yet. Tap <code>/quiz</code> in chat to start.</div>'}
    </div>

  </main>

<script>
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor?.('secondary_bg_color'); } catch(e) {}
    try { tg.setBackgroundColor?.(getComputedStyle(document.documentElement).getPropertyValue('--tg-bg').trim()); } catch(e) {}
    tg.MainButton.setText('📚 Back to chat').show();
    tg.MainButton.onClick(() => { tg.HapticFeedback?.impactOccurred('medium'); tg.close(); });
  }

  // Count-up animations
  const elements = document.querySelectorAll('[data-count]');
  elements.forEach(el => {
    const target = +el.dataset.count;
    if (target === 0) { el.textContent = '0'; return; }
    let cur = 0;
    const start = performance.now();
    const dur = 900;
    const ease = (t) => 1 - Math.pow(1 - t, 3);
    const tick = (now) => {
      const t = Math.min(1, (now - start) / dur);
      cur = Math.round(target * ease(t));
      el.textContent = cur;
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });

  // Animate score bars after mount
  requestAnimationFrame(() => {
    document.querySelectorAll('.sb-fill[data-fill]').forEach(el => {
      el.style.width = el.dataset.fill + '%';
    });
  });

  // Chart.js defaults
  const fg = getComputedStyle(document.documentElement).getPropertyValue('--tg-fg').trim();
  const hint = getComputedStyle(document.documentElement).getPropertyValue('--tg-hint').trim();
  Chart.defaults.color = fg;
  Chart.defaults.borderColor = 'rgba(255,255,255,0.08)';
  Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, Inter, SF Pro Text, Segoe UI, sans-serif';
  Chart.defaults.font.size = 11;

  const D = ${JSON.stringify(chartData)};

  // Doughnut: difficulty mix
  if (D.diff.some(v => v > 0)) {
    new Chart(document.getElementById('diffChart'), {
      type: 'doughnut',
      data: {
        labels: ['Beginner','Intermediate','Advanced'],
        datasets: [{
          data: D.diff,
          backgroundColor: ['#34c759','#ffcc00','#ff453a'],
          borderWidth: 0,
          hoverOffset: 6
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: true,
        cutout: '62%',
        animation: { animateRotate: true, animateScale: true, duration: 1000 },
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, padding: 12, font: { size: 11, weight: '500' } } },
          tooltip: { backgroundColor: 'rgba(0,0,0,0.85)', padding: 10, cornerRadius: 8 }
        }
      }
    });
  } else {
    const c = document.getElementById('diffChart').parentElement;
    c.querySelector('canvas').remove();
    c.insertAdjacentHTML('beforeend', '<div class="empty">No materials yet.</div>');
  }

  // Line: score trend
  if (D.scores.length) {
    const ctx = document.getElementById('trendChart').getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, 180);
    grad.addColorStop(0, 'rgba(91,138,255,0.40)');
    grad.addColorStop(1, 'rgba(91,138,255,0)');
    new Chart(ctx, {
      type: 'line',
      data: {
        labels: D.labels,
        datasets: [{
          data: D.scores,
          borderColor: '#5b8aff',
          backgroundColor: grad,
          tension: 0.4,
          fill: true,
          pointRadius: 4,
          pointHoverRadius: 6,
          pointBackgroundColor: '#5b8aff',
          pointBorderColor: '#fff',
          pointBorderWidth: 2,
          borderWidth: 3
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: true,
        animation: { duration: 1100, easing: 'easeOutCubic' },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(0,0,0,0.85)', padding: 10, cornerRadius: 8,
            callbacks: { title: (ctx) => D.titles[ctx[0].dataIndex] || '' }
          }
        },
        scales: {
          y: { min: 0, max: 100, ticks: { callback: v => v + '%', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
          x: { ticks: { font: { size: 10 } }, grid: { display: false } }
        }
      }
    });
  } else {
    const c = document.getElementById('trendChart').parentElement;
    c.querySelector('canvas').remove();
    c.insertAdjacentHTML('beforeend', '<div class="empty">No quizzes yet.</div>');
  }

  // Haptic feedback on KPI tap
  document.querySelectorAll('.kpi').forEach(el => {
    el.addEventListener('click', () => tg?.HapticFeedback?.impactOccurred?.('light'));
  });
</script>
</body>
</html>`;

return [{ json: { html } }];"""

# Apply patches
patches_js = {
    'ans: format results': FORMAT_RESULTS_JS,
    'miniapp: render HTML': MINIAPP_RENDER_JS,
}
patches_q = {
    'miniapp: pg load': MINIAPP_PG_SQL,
}

count = 0
for n in nodes:
    name = n.get('name', '')
    if name in patches_js:
        n['parameters']['jsCode'] = patches_js[name]
        sys.stderr.write(f"Patched jsCode: {name}\n"); count += 1
    if name in patches_q:
        n['parameters']['query'] = patches_q[name]
        sys.stderr.write(f"Patched query: {name}\n"); count += 1

sys.stderr.write(f"Total: {count}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
