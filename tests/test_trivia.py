"""Unit tests for the Trivia plugin's pure logic and game state.

These exercise the pieces that don't need a live Discord connection:
question parsing/normalization, fallback bank filtering, score persistence,
leaderboard ordering, reputation awarding (with caps), and the in-memory
answer flow.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import load_plugin_module


@pytest.fixture
def trivia():
    """A TriviaPlugin instance bound to a fake bot/context."""
    module = load_plugin_module()

    class FakeReputation:
        enabled = True

        def __init__(self):
            self.calls = []

        async def _add_points(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    class FakeBot:
        def __init__(self):
            from services.bark_context import BarkContext
            from services.event_bus import EventBus

            self._eb = EventBus()
            self.rep = FakeReputation()
            self._ctx = BarkContext(self, self._eb)

        @property
        def modules(self):
            return SimpleNamespace(get_module=lambda name: self.rep if name == "reputation" else None)

    bot = FakeBot()
    plugin = module.TriviaPlugin(bot._ctx)
    plugin.rep = bot.rep
    return plugin


def _session(trivia, **overrides):
    """Build a _TriviaSession with sensible defaults."""
    module = load_plugin_module()
    defaults = {
        "guild_id": 1,
        "channel_id": 100,
        "questions": [
            {
                "question": "What is 2+2?",
                "options": ["3", "4", "5", "6"],
                "answer": 1,
                "category": "mathematics",
                "difficulty": "easy",
            },
            {
                "question": "What color is the sky?",
                "options": ["Green", "Blue", "Red", "Yellow"],
                "answer": 1,
                "category": "general_knowledge",
                "difficulty": "easy",
            },
        ],
        "starter_id": 1,
        "time_per_question": 20,
        "points_per_correct": 5,
        "first_bonus": 2,
        "rep_per_correct": 2,
        "rep_cap": 10,
    }
    defaults.update(overrides)
    return module._TriviaSession(**defaults)


class FakeInteraction:
    def __init__(self, user_id: int, name: str, channel_id: int = 100):
        self.user = SimpleNamespace(id=user_id, display_name=name)
        self.channel = SimpleNamespace(id=channel_id)
        self.response = FakeResponse()
        self.followup = FakeFollowup()


class FakeResponse:
    def __init__(self):
        self.done = False
        self.sent = None
        self.deferred = False

    def is_done(self):
        return self.done

    async def send_message(self, content, ephemeral=False):
        self.done = True
        self.sent = content

    async def defer(self, ephemeral=False):
        self.done = True
        self.deferred = True


class _FakeMessage:
    def __init__(self, message_id: int):
        self.id = message_id


class FakeFollowup:
    _next_id = 1000

    def __init__(self):
        self.sent = None
        self.edits = []

    async def send(self, content, ephemeral=False):
        self.sent = content
        FakeFollowup._next_id += 1
        return _FakeMessage(FakeFollowup._next_id)

    async def edit_message(self, message_id, content=None, **kwargs):
        self.edits.append((message_id, content))


# ── Question source ───────────────────────────────────


def test_parse_opentdb_unescapes_and_shuffles(trivia):
    item = {
        "question": "What is &quot;life&quot;?",
        "correct_answer": "42 &amp; 7",
        "incorrect_answers": ["a", "b", "c"],
        "category": "Science: Computers",
        "category_id": 18,
        "difficulty": "easy",
        "type": "multiple",
    }
    parsed = trivia._parse_opentdb(item)
    assert parsed["question"] == 'What is "life"?'
    assert parsed["options"][parsed["answer"]] == "42 & 7"
    assert sorted(parsed["options"]) == sorted(["42 & 7", "a", "b", "c"])
    assert parsed["category"] == "computers"
    assert parsed["difficulty"] == "easy"


def test_parse_opentdb_maps_category_name_to_slug(trivia):
    parsed = trivia._parse_opentdb(
        {
            "question": "Q",
            "correct_answer": "Right",
            "incorrect_answers": ["W1", "W2", "W3"],
            "category": "Entertainment: Video Games",
            "difficulty": "easy",
        }
    )
    assert parsed["category"] == "video_games"


def test_parse_opentdb_correct_answer_appears_once(trivia):
    parsed = trivia._parse_opentdb(
        {
            "question": "Q",
            "correct_answer": "Right",
            "incorrect_answers": ["W1", "W2", "W3"],
            "category_id": 9,
            "difficulty": "hard",
        }
    )
    assert parsed["options"].count("Right") == 1
    assert parsed["options"][parsed["answer"]] == "Right"
    assert len(parsed["options"]) == 4


def test_fallback_questions_respect_category_and_count(trivia):
    pool = trivia._fallback_questions(17, "easy", 3)  # science_nature easy
    assert len(pool) == 3
    assert all(item["category"] == "science_nature" for item in pool)
    assert all(item["difficulty"] == "easy" for item in pool)


def test_fallback_questions_fill_beyond_pool(trivia):
    # "any" category, 20 requested (the game cap) — the bank holds 24.
    pool = trivia._fallback_questions(0, "any", 20)
    assert len(pool) == 20
    assert all({"question", "options", "answer"} <= set(item) for item in pool)


def test_fallback_questions_each_have_valid_answer(trivia):
    for item in trivia._fallback_questions(0, "any", 30):
        assert 0 <= item["answer"] < len(item["options"])


# ── Persistence ───────────────────────────────────────


@pytest.mark.asyncio
async def test_save_scores_accumulates_across_games(db, trivia):
    await trivia.enable()
    session = _session(trivia)
    session.points = {1: 7, 2: 5}
    session.correct_count = {1: 2, 2: 1}
    session.answered_count = {1: 2, 2: 2}
    session.streak = {1: 4, 2: 0}
    session.names = {1: "Alice", 2: "Bob"}
    await trivia._save_scores(session)

    rows = await trivia._top_scores(1, 10)
    assert len(rows) == 2
    alice = next(row for row in rows if row["user_id"] == "1")
    assert alice["points"] == 7
    assert alice["correct"] == 2
    assert alice["games_played"] == 1
    assert alice["best_streak"] == 4

    # Second game accumulates and keeps the best streak.
    session2 = _session(trivia)
    session2.points = {1: 5, 2: 5}
    session2.correct_count = {1: 1, 2: 1}
    session2.answered_count = {1: 1, 2: 2}
    session2.streak = {1: 2, 2: 0}
    session2.names = {1: "Alice", 2: "Bob"}
    await trivia._save_scores(session2)

    rows = await trivia._top_scores(1, 10)
    alice = next(row for row in rows if row["user_id"] == "1")
    assert alice["points"] == 12
    assert alice["correct"] == 3
    assert alice["games_played"] == 2
    assert alice["best_streak"] == 4  # max(4, 2)


@pytest.mark.asyncio
async def test_top_scores_orders_by_points_then_correct(db, trivia):
    await trivia.enable()
    s1 = _session(trivia)
    s1.points = {1: 10, 2: 20, 3: 10}
    s1.correct_count = {1: 2, 2: 4, 3: 3}
    s1.answered_count = {1: 3, 2: 4, 3: 3}
    s1.names = {1: "A", 2: "B", 3: "C"}
    await trivia._save_scores(s1)

    rows = await trivia._top_scores(1, 10)
    assert [row["user_id"] for row in rows] == ["2", "3", "1"]  # 20, then 10-by-correct


@pytest.mark.asyncio
async def test_player_stats_returns_none_when_absent(db, trivia):
    await trivia.enable()
    assert await trivia._player_stats(1, 999) is None


@pytest.mark.asyncio
async def test_player_stats_returns_row_when_present(db, trivia):
    await trivia.enable()
    session = _session(trivia)
    session.points = {1: 12}
    session.correct_count = {1: 3}
    session.answered_count = {1: 4}
    session.streak = {1: 2}
    session.names = {1: "Alice"}
    await trivia._save_scores(session)

    stats = await trivia._player_stats(1, 1)
    assert stats is not None
    assert stats["points"] == 12
    assert stats["correct"] == 3
    assert stats["answered"] == 4
    assert stats["best_streak"] == 2
    assert stats["display_name"] == "Alice"


# ── Reputation integration ────────────────────────────


@pytest.mark.asyncio
async def test_award_reputation_applies_session_cap(db, trivia):
    await trivia.enable()
    session = _session(trivia, rep_per_correct=2, rep_cap=10)
    session.correct_count = {1: 3, 2: 10}  # 6 and 20 -> capped at 10
    summary = await trivia._award_reputation(session)
    amounts = {int(call[0][1]): call[0][2] for call in trivia.rep.calls}
    assert amounts == {1: 6.0, 2: 10.0}
    assert "2 players" in summary


@pytest.mark.asyncio
async def test_award_reputation_skips_when_rep_disabled(db, trivia):
    await trivia.enable()
    trivia.rep.enabled = False
    session = _session(trivia)
    session.correct_count = {1: 5}
    summary = await trivia._award_reputation(session)
    assert trivia.rep.calls == []
    assert summary == ""


@pytest.mark.asyncio
async def test_award_reputation_skips_when_rep_points_zero(db, trivia):
    await trivia.enable()
    session = _session(trivia, rep_per_correct=0, rep_cap=10)
    session.correct_count = {1: 5}
    assert await trivia._award_reputation(session) == ""
    assert trivia.rep.calls == []


# ── Question sources ──────────────────────────────────


def test_parse_triviaapi_normalizes_item(trivia):
    item = {
        "category": "science",
        "correctAnswer": "Oxygen",
        "incorrectAnswers": ["Hydrogen", "Helium", "Carbon"],
        "question": {"text": "What element has atomic number 8?"},
        "difficulty": "easy",
        "type": "text_choice",
    }
    parsed = trivia._parse_triviaapi(item)
    assert parsed is not None
    assert parsed["question"] == "What element has atomic number 8?"
    assert parsed["options"][parsed["answer"]] == "Oxygen"
    assert parsed["category"] == "science_nature"  # reverse-mapped to our slug
    assert parsed["difficulty"] == "easy"


def test_parse_triviaapi_rejects_unusable_item(trivia):
    assert trivia._parse_triviaapi({"category": "science", "difficulty": "easy"}) is None
    assert trivia._parse_triviaapi({"question": {"text": "x"}, "correctAnswer": "y"}) is None


def test_settings_schema_exposes_sources(trivia):
    props = trivia.get_settings_schema()["properties"]
    for key in ("source_opentdb", "source_triviaapi", "source_builtin"):
        assert key in props
        assert props[key]["type"] == "boolean"
        assert props[key]["default"] is True


def test_leaderboard_table_shape(trivia):
    table = trivia._leaderboard_table([])
    assert table["columns"] == ["#", "Player", "Points", "Correct", "Accuracy", "Games"]
    assert table["rows"] == []

    rows = [
        {"user_id": "1", "display_name": "Alice", "points": 12, "correct": 3, "answered": 4, "games_played": 2},
        {"user_id": "2", "display_name": None, "points": 5, "correct": 1, "answered": 2, "games_played": 1},
    ]
    table = trivia._leaderboard_table(rows)
    assert table["rows"][0] == ["1", "Alice", "12", "3/4", "75%", "2"]
    assert table["rows"][1] == ["2", "<user 2>", "5", "1/2", "50%", "1"]


def test_leaderboard_action_marks_auto_run(trivia):
    leaderboard = next(a for a in trivia.get_actions() if a["id"] == "leaderboard")
    assert leaderboard["auto_run"] is True


@pytest.mark.asyncio
async def test_build_pool_uses_all_enabled_sources(db, trivia):
    await trivia.enable()
    # Stub the network sources; builtin is real.
    trivia._fetch_questions = _stub_fetch([{"question": "OTDB Q", "correct_answer": "A",
        "incorrect_answers": ["B", "C", "D"], "category_id": 9, "difficulty": "easy"}])
    trivia._fetch_triviaapi = _stub_fetch([{"category": "science", "correctAnswer": "A",
        "incorrectAnswers": ["B", "C", "D"], "question": {"text": "TAPI Q"}, "difficulty": "easy"}])

    pool = await trivia._build_question_pool(9, "easy", 5, {})
    assert len(pool) == 5  # 1 opentdb + 1 triviaapi + 3 builtin
    assert {q["source"] for q in pool} == {"opentdb", "triviaapi", "builtin"}
    assert all("source" in q for q in pool)


@pytest.mark.asyncio
async def test_build_pool_respects_disabled_sources(db, trivia):
    await trivia.enable()
    trivia._fetch_questions = _stub_fetch([{"question": "OTDB Q", "correct_answer": "A",
        "incorrect_answers": ["B", "C", "D"], "category_id": 9, "difficulty": "easy"}])
    trivia._fetch_triviaapi = _stub_fetch([{"category": "science", "correctAnswer": "A",
        "incorrectAnswers": ["B", "C", "D"], "question": {"text": "TAPI Q"}, "difficulty": "easy"}])

    pool = await trivia._build_question_pool(
        9, "easy", 5, {"source_opentdb": False, "source_triviaapi": False}
    )
    assert len(pool) == 5
    assert all(q["source"] == "builtin" for q in pool)


@pytest.mark.asyncio
async def test_build_pool_all_disabled_returns_empty(db, trivia):
    await trivia.enable()
    pool = await trivia._build_question_pool(
        9, "easy", 5,
        {"source_opentdb": False, "source_triviaapi": False, "source_builtin": False},
    )
    assert pool == []


@pytest.mark.asyncio
async def test_build_pool_skips_failing_source(db, trivia):
    await trivia.enable()

    async def _fail(*args, **kwargs):
        return []

    trivia._fetch_questions = _fail
    trivia._fetch_triviaapi = _fail
    pool = await trivia._build_question_pool(0, "any", 4, {})
    assert len(pool) == 4
    assert all(q["source"] == "builtin" for q in pool)


def _stub_fetch(items):
    async def _fetch(*args, **kwargs):
        return items

    return _fetch


# ── In-memory answer flow ─────────────────────────────


@pytest.mark.asyncio
async def test_answer_flow_correct_wrong_first_bonus_and_dupes(trivia):
    session = _session(trivia, points_per_correct=5, first_bonus=2)
    trivia._sessions[100] = session
    session.closed = False
    session.index = 0  # question 0: answer = index 1 ("4")

    # Alice answers correctly first -> 5 + 2 bonus. Feedback is a followup.
    alice = FakeInteraction(1, "Alice")
    await trivia._on_answer(alice, 0, 1)
    assert session.points[1] == 7
    assert session.first_correct == 1
    assert alice.followup.sent is not None
    assert "Correct" in alice.followup.sent and "7" in alice.followup.sent
    assert 1 in session.guess_messages

    # Bob answers correctly after -> no bonus.
    bob = FakeInteraction(2, "Bob")
    await trivia._on_answer(bob, 0, 1)
    assert session.points[2] == 5
    assert "Correct" in bob.followup.sent

    # Alice clicks again (a NEW interaction, like a real second button click)
    # -> rejected, no double count (this path stays a one-off ephemeral).
    alice_again = FakeInteraction(1, "Alice")
    await trivia._on_answer(alice_again, 0, 0)
    assert session.answered_count[1] == 1
    assert session.points[1] == 7
    assert "already answered" in alice_again.response.sent

    # Carol answers wrong -> streak reset, no points.
    carol = FakeInteraction(3, "Carol")
    await trivia._on_answer(carol, 0, 0)
    assert session.points.get(3) is None
    assert session.streak[3] == 0
    assert "Not quite" in carol.followup.sent


@pytest.mark.asyncio
async def test_guess_feedback_edits_existing_message(trivia):
    session = _session(trivia, points_per_correct=5, first_bonus=2)
    trivia._sessions[100] = session
    session.closed = False
    session.index = 0
    # Q2 (index 1) is the sky question: answer index 1 = "Blue".

    alice = FakeInteraction(1, "Alice")
    await trivia._on_answer(alice, 0, 1)
    first_id = session.guess_messages[1]
    assert first_id is not None

    # Second question, Alice answers again -> the SAME message gets edited,
    # no new message is sent. (_post_question clears `answered` per question.)
    session.index = 1
    session.closed = False
    session.answered.clear()
    alice2 = FakeInteraction(1, "Alice")
    await trivia._on_answer(alice2, 1, 1)
    assert session.guess_messages[1] == first_id
    assert alice2.followup.sent is None, "must not send a new feedback message"
    assert alice2.followup.edits, "must edit the previous feedback message"
    edited_id, edited_content = alice2.followup.edits[-1]
    assert edited_id == first_id
    assert "Q2" in edited_content
    # Tally shows both results.
    assert "Q1 ✅" in edited_content and "Q2 ✅" in edited_content


@pytest.mark.asyncio
async def test_answer_flow_rejects_closed_question(trivia):
    session = _session(trivia)
    trivia._sessions[100] = session
    session.closed = True
    session.index = 0
    actor = FakeInteraction(1, "Alice")
    await trivia._on_answer(actor, 0, 1)
    assert session.answered == {}
    assert "closed" in actor.response.sent


@pytest.mark.asyncio
async def test_answer_flow_rejects_missing_session(trivia):
    actor = FakeInteraction(1, "Alice", channel_id=999)
    await trivia._on_answer(actor, 0, 1)
    assert actor.response.sent is not None
    assert "no trivia running" in actor.response.sent.lower()


def test_standing_snippet_ranks_highest_first(trivia):
    session = _session(trivia)
    session.points = {1: 5, 2: 12, 3: 8}
    session.names = {1: "Alice", 2: "Bob", 3: "Carol"}
    snippet = trivia._standing_snippet(session, limit=2)
    assert snippet.index("Bob") < snippet.index("Carol")
    assert "Alice" not in snippet
