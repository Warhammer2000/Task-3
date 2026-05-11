// n8n Code node — Format Teacher summary as Telegram MarkdownV2
//
// Input: { url, title, summary_json: { key_points[], main_concepts[],
//          difficulty, interview_angle }, material_id }
// Output: { chat_id, text, reply_markup } — ready for sendMessage with
//          parse_mode = "MarkdownV2"
//
// MarkdownV2 escape rules: _ * [ ] ( ) ~ ` > # + - = | { } . ! must be
// backslash-escaped outside specific entities. We escape conservatively
// across all user-facing strings.

function escapeMD(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/([_*\[\]()~`>#+\-=|{}.!\\])/g, '\\$1');
}

const data = $input.first().json;
const chatId = $input.first().json.chat_id;
const materialId = data.material_id;
const summary = data.summary_json;

const diffEmoji = {
  beginner:     '🟢',
  intermediate: '🟡',
  advanced:     '🔴',
}[summary.difficulty] || '⚪️';

const keyPointsBlock = summary.key_points
  .map((p, i) => `${i + 1}\\. ${escapeMD(p)}`)
  .join('\n');

const conceptsBlock = summary.main_concepts
  .map((c) => `\`${escapeMD(c)}\``)
  .join(' · ');

// MarkdownV2 spoiler: ||hidden text||
const interviewBlock = `||💡 Interview angle: ${escapeMD(summary.interview_angle)}||`;

const text =
  `📚 *${escapeMD(summary.title || data.title || 'Untitled')}*\n` +
  `${diffEmoji} *${escapeMD(summary.difficulty)}*\n\n` +
  `*Key points:*\n${keyPointsBlock}\n\n` +
  `*Concepts:* ${conceptsBlock}\n\n` +
  `${interviewBlock}\n\n` +
  `_Tap below to test yourself with 5 interview-style questions\\._`;

// Inline keyboard — "Take quiz now" button kicks off the inline-after-learning
// quiz trigger (brief R16). callback_data references the material_id.
const reply_markup = {
  inline_keyboard: [
    [
      {
        text: '🎯 Take quiz now',
        callback_data: `quiz:start:${materialId}`,
      },
    ],
  ],
};

return [{ json: { chat_id: chatId, text, reply_markup } }];
