-- AI Challenge 2.0 · Task 3 — application schema
--
-- Runs once on first Postgres container boot via /docker-entrypoint-initdb.d.
-- All project tables live in the same database as n8n's metadata; we keep
-- them in the `app` schema to avoid clashing with n8n's own tables.

CREATE SCHEMA IF NOT EXISTS app;
SET search_path = app, public;

-- =========================================================================
-- learning_materials — every URL the user has /learn-ed
-- =========================================================================
CREATE TABLE IF NOT EXISTS app.learning_materials (
    id            BIGSERIAL PRIMARY KEY,
    chat_id       BIGINT      NOT NULL,                       -- Telegram chat / user id
    url           TEXT        NOT NULL,
    title         TEXT        NOT NULL,
    content       TEXT        NOT NULL,                       -- extracted clean text
    summary_json  JSONB       NOT NULL,                       -- key_points[], concepts[], difficulty
    difficulty    TEXT        NOT NULL
        CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chat_id, url)                                     -- one row per (user, url)
);

CREATE INDEX IF NOT EXISTS idx_materials_chat
    ON app.learning_materials (chat_id, added_at DESC);

-- =========================================================================
-- quizzes — one row per quiz attempt (a quiz = 5 questions for one material)
-- =========================================================================
CREATE TABLE IF NOT EXISTS app.quizzes (
    id            BIGSERIAL PRIMARY KEY,
    material_id   BIGINT      NOT NULL
        REFERENCES app.learning_materials(id) ON DELETE CASCADE,
    chat_id       BIGINT      NOT NULL,
    questions     JSONB       NOT NULL,                       -- [{id, question, options{A..D}, correctAnswer, explanation}]
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    score_pct     INTEGER     CHECK (score_pct BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS idx_quizzes_chat_started
    ON app.quizzes (chat_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_quizzes_material
    ON app.quizzes (material_id);

-- =========================================================================
-- quiz_answers — one row per answered question
-- =========================================================================
CREATE TABLE IF NOT EXISTS app.quiz_answers (
    id            BIGSERIAL PRIMARY KEY,
    quiz_id       BIGINT      NOT NULL
        REFERENCES app.quizzes(id) ON DELETE CASCADE,
    question_id   TEXT        NOT NULL,                       -- e.g. "Q1"
    user_answer   TEXT        NOT NULL,                       -- A / B / C / D (or raw if free-form)
    correct       BOOLEAN     NOT NULL,
    answered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (quiz_id, question_id)
);

-- =========================================================================
-- user_state — short-lived conversation state per chat_id
-- =========================================================================
-- Used so the bot knows whether the user is mid-quiz (which Q they're on),
-- mid-topic-select, etc. n8n is stateless across nodes; state lives here.

CREATE TABLE IF NOT EXISTS app.user_state (
    chat_id        BIGINT PRIMARY KEY,
    state          TEXT        NOT NULL DEFAULT 'idle',       -- idle | awaiting_url | quiz_in_progress | topic_select
    active_quiz_id BIGINT      REFERENCES app.quizzes(id) ON DELETE SET NULL,
    current_q      TEXT,                                       -- e.g. "Q3"
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =========================================================================
-- material_reactions — Telegram message reactions captured on summary messages
-- =========================================================================
-- Wow feature: when user 👍/👎/❤️ on a Teacher summary message, store the
-- reaction. Surfaced in /stats as "most loved topics" / "topics you bounced off".

CREATE TABLE IF NOT EXISTS app.material_reactions (
    id             BIGSERIAL PRIMARY KEY,
    material_id    BIGINT      NOT NULL
        REFERENCES app.learning_materials(id) ON DELETE CASCADE,
    chat_id        BIGINT      NOT NULL,
    reaction_emoji TEXT        NOT NULL,
    reacted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (material_id, chat_id, reaction_emoji)
);

-- =========================================================================
-- Helper view: per-chat /stats summary
-- =========================================================================
CREATE OR REPLACE VIEW app.v_user_stats AS
SELECT
    m.chat_id,
    COUNT(DISTINCT m.id)                            AS materials_count,
    COUNT(DISTINCT q.id)                            AS quizzes_taken,
    ROUND(AVG(q.score_pct))::INT                    AS avg_score_pct,
    MAX(q.finished_at)                              AS last_quiz_at,
    SUM(CASE WHEN m.difficulty = 'advanced' THEN 1 ELSE 0 END)     AS advanced_materials,
    SUM(CASE WHEN m.difficulty = 'intermediate' THEN 1 ELSE 0 END) AS intermediate_materials,
    SUM(CASE WHEN m.difficulty = 'beginner' THEN 1 ELSE 0 END)     AS beginner_materials
FROM app.learning_materials m
LEFT JOIN app.quizzes q
       ON q.material_id = m.id
      AND q.finished_at IS NOT NULL
GROUP BY m.chat_id;
