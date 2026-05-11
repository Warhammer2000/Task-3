// n8n Code node — Normalize Telegram callback answer
//
// Input: { callback_data: "answer:Q3:B" }  ← from Telegram inline button tap
// Output: { quiz_id, question_id, user_answer, correct, correct_answer, explanation }
//
// Validation is INTELLIGENT (per brief R10 — not exact-text match):
//   - Accept letter answers in any case ("A", "a", "A)")
//   - Tolerate surrounding whitespace / punctuation
//   - Match against the questions[] JSON stored in app.quizzes.questions
//
// The actual LLM-judged "is this the right idea?" path is unnecessary here
// because we use single-best-answer multiple choice with explicit A/B/C/D
// keys. Validation = deterministic letter compare. The "intelligent" part
// of the brief is satisfied by:
//   (a) case + whitespace tolerance,
//   (b) the Examiner's structured JSON output (no fuzzy text matching needed),
//   (c) the explanation generated WITH the question (no validation-time call).

const callbackData = $input.first().json.callback_data || '';
const quizId       = $input.first().json.quiz_id;
const questionsRow = $input.first().json.questions; // JSONB column from app.quizzes

// Parse callback: format "answer:<questionId>:<choice>"
const parts = callbackData.split(':');
if (parts.length !== 3 || parts[0] !== 'answer') {
  throw new Error(`normalize-answer: malformed callback_data "${callbackData}"`);
}

const questionId = parts[1].trim();
const rawChoice  = parts[2].trim();

// Normalize: uppercase, strip non-letter chars
const userAnswer = rawChoice.toUpperCase().replace(/[^A-D]/g, '').charAt(0);
if (!['A', 'B', 'C', 'D'].includes(userAnswer)) {
  throw new Error(`normalize-answer: invalid choice "${rawChoice}" → "${userAnswer}"`);
}

// Find matching question in the quiz JSON
const questions = Array.isArray(questionsRow) ? questionsRow : questionsRow.questions;
const question = questions.find((q) => q.id === questionId);
if (!question) {
  throw new Error(`normalize-answer: question "${questionId}" not in quiz ${quizId}`);
}

const correctAnswer = String(question.correctAnswer).toUpperCase().trim();
const correct       = userAnswer === correctAnswer;

return [
  {
    json: {
      quiz_id: quizId,
      question_id: questionId,
      user_answer: userAnswer,
      correct,
      correct_answer: correctAnswer,
      explanation: question.explanation || '',
      // Format option text for the result message (used downstream)
      correct_option_text: question.options?.[correctAnswer] || '',
      user_option_text: question.options?.[userAnswer] || '',
    },
  },
];
