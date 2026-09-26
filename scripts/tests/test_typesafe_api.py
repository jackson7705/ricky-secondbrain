"""Tests for the TypeSafe judgment layer — no network; the client is faked."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from integrations import typesafe_api as ts


class FakeClient:
    """Answers each question from a canned map, recording what was asked."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def system_one(self, state: Any, questions: dict[str, Any]) -> Any:
        self.calls.append((state, dict(questions)))
        return SimpleNamespace(
            model="jev-test",
            usage=SimpleNamespace(input_tokens=10, output_tokens=0),
            answers={qid: self.answers[qid] for qid in questions},
        )


def noul(p: float) -> Any:
    return SimpleNamespace(type="noul", noul=p)


def choice(pick: str, confidence: float) -> Any:
    return SimpleNamespace(
        type="choice", choice=pick, confidence=confidence, probabilities={pick: 1.0}
    )


def score(value: float, confidence: float = 0.9) -> Any:
    return SimpleNamespace(
        type="score", score=value, confidence=confidence, probabilities={}, legend={}
    )


RUBRIC: dict[str, Any] = {
    "name": "t",
    "pass_score": 75,
    "dimensions": {
        "fit": {
            "weight": 3,
            "requires_brief": True,
            "instructions": "q",
            "levels": ["a", "b", "c"],
        },
        "clarity": {"weight": 1, "instructions": "q", "levels": ["a", "b", "c"]},
    },
    "blockers": {"placeholder": {"instructions": "q"}},
}


def review_client(fit: float, clarity: float, placeholder: float) -> FakeClient:
    return FakeClient(
        {"d:fit": score(fit), "d:clarity": score(clarity), "b:placeholder": noul(placeholder)}
    )


# =============================================================================
# Question building
# =============================================================================


class TestBuildQuestion:
    def test_builds_each_type(self) -> None:
        assert ts.build_question({"type": "noul", "instructions": "q"}).type == "noul"
        built = ts.build_question(
            {"type": "choice", "instructions": "q", "criteria": {"a": None, "b": "desc"}}
        )
        assert built.type == "choice"
        built = ts.build_question({"type": "score", "instructions": "q", "criteria": ["lo", "hi"]})
        assert built.type == "score"

    @pytest.mark.parametrize(
        "spec",
        [
            {"type": "noul"},
            {"type": "choice", "instructions": "q", "criteria": {"only": None}},
            {"type": "score", "instructions": "q", "criteria": ["one"]},
            {"type": "score", "instructions": "q", "criteria": "lo,hi"},
            {"type": "essay", "instructions": "q"},
        ],
    )
    def test_rejects_malformed_specs(self, spec: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            ts.build_question(spec)


class TestAsk:
    def test_rejects_oversized_state_before_calling(self) -> None:
        client = FakeClient({})
        with pytest.raises(ValueError, match="Split it"):
            ts.ask(
                "x" * (ts.MAX_STATE_CHARS + 1),
                {"q": {"type": "noul", "instructions": "q"}},
                client=client,
            )
        assert client.calls == []

    def test_not_configured_raises_clear_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ts, "TYPESAFE_API_KEY", "")
        with pytest.raises(ts.TypeSafeNotConfiguredError):
            ts.get_client()


# =============================================================================
# Uncertainty
# =============================================================================


class TestUncertainty:
    def test_noul_near_half_is_uncertain(self) -> None:
        assert ts.Judgment("q", "noul", 0.5).uncertain
        assert not ts.Judgment("q", "noul", 0.95).uncertain
        assert not ts.Judgment("q", "noul", 0.05).uncertain

    def test_choice_below_floor_is_uncertain(self) -> None:
        assert ts.Judgment("q", "choice", "a", confidence=0.4).uncertain
        assert not ts.Judgment("q", "choice", "a", confidence=0.9).uncertain


# =============================================================================
# Recipes
# =============================================================================


class TestDecide:
    def test_allow_none_adds_no_match_option(self) -> None:
        client = FakeClient({"decision": choice(ts.NO_MATCH, 0.9)})
        result = ts.decide("s", "which?", {"a": "A", "b": "B"}, allow_none=True, client=client)
        asked = client.calls[0][1]["decision"]
        assert ts.NO_MATCH in asked.criteria
        assert result.value == ts.NO_MATCH


class TestCheck:
    def test_missing_quote_is_fabricated_without_asking_the_model(self) -> None:
        client = FakeClient({})
        verdicts = ts.check(
            "Revenue grew 12% in Q2.",
            [{"claim": "Revenue grew", "quote": "Revenue grew 40%"}],
            client=client,
        )
        assert verdicts[0].verdict == "fabricated_quote"
        assert verdicts[0].needs_review
        assert client.calls == []

    def test_quote_matches_across_line_wraps_and_curly_quotes(self) -> None:
        client = FakeClient({"0": choice("supported", 0.95)})
        verdicts = ts.check(
            "The client said “we\nrenew in March”.",
            [{"claim": "Renewal is in March", "quote": 'said "we renew in March"'}],
            client=client,
        )
        assert verdicts[0].verdict == "supported"
        assert not verdicts[0].needs_review

    def test_order_preserved_and_unsupported_flagged(self) -> None:
        client = FakeClient({"0": choice("contradicted", 0.99), "2": choice("supported", 0.5)})
        verdicts = ts.check(
            "evidence",
            ["first", {"claim": "second", "quote": "not in there"}, "third"],
            client=client,
        )
        assert [v.claim for v in verdicts] == ["first", "second", "third"]
        assert [v.verdict for v in verdicts] == ["contradicted", "fabricated_quote", "supported"]
        # Confident contradiction and low-confidence support both need a look.
        assert all(v.needs_review for v in verdicts)


class TestReview:
    def test_weighted_composite_and_pass(self) -> None:
        client = review_client(2.0, 1.0, 0.0)
        result = ts.review("doc", RUBRIC, brief="do x", client=client)
        # (1.0 * 3 + 0.5 * 1) / 4 = 87.5
        assert result.score == 87.5
        assert result.verdict == "pass"

    def test_blocker_fails_a_high_score(self) -> None:
        client = review_client(2.0, 2.0, 0.95)
        result = ts.review("doc", RUBRIC, brief="do x", client=client)
        assert result.score == 100.0
        assert result.verdict == "revise"
        assert result.blockers["placeholder"]["status"] == "triggered"

    def test_unsure_blocker_asks_for_a_check(self) -> None:
        client = review_client(2.0, 2.0, 0.5)
        assert ts.review("doc", RUBRIC, brief="do x", client=client).verdict == "check"

    def test_low_score_needs_revision(self) -> None:
        client = review_client(0.5, 1.0, 0.0)
        assert ts.review("doc", RUBRIC, brief="do x", client=client).verdict == "revise"

    def test_brief_dependent_questions_skipped_without_brief(self) -> None:
        client = FakeClient({"d:clarity": score(2.0), "b:placeholder": noul(0.0)})
        result = ts.review("doc", RUBRIC, client=client)
        assert result.skipped == ["fit"]
        assert "d:fit" not in client.calls[0][1]
        assert result.score == 100.0

    def test_improvement_hint_points_at_the_next_level(self) -> None:
        client = review_client(0.7, 2.0, 0.0)
        dim = ts.review("doc", RUBRIC, brief="do x", client=client).dimensions["fit"]
        assert (dim["level"], dim["next_level"]) == ("b", "c")

    @pytest.mark.parametrize(
        "name", ["deliverable", "email-reply", "seo-article", "research-brief"]
    )
    def test_shipped_rubrics_build_valid_questions(self, name: str) -> None:
        rubric = ts.load_rubric(name)
        assert name in ts.list_rubrics()
        for item in rubric["dimensions"].values():
            ts.build_question(
                {"type": "score", "instructions": item["instructions"], "criteria": item["levels"]}
            )
        for item in rubric["blockers"].values():
            ts.build_question({"type": "noul", "instructions": item["instructions"]})

    def test_unknown_rubric_lists_what_exists(self) -> None:
        with pytest.raises(FileNotFoundError, match="deliverable"):
            ts.load_rubric("nope")


class TestRank:
    def test_sorted_by_relevance(self) -> None:
        client = FakeClient({"a": score(0.0), "b": score(3.0), "c": score(1.5)})
        ranked = ts.rank("q", {"a": "x", "b": "y", "c": "z"}, client=client)
        assert [r.id for r in ranked] == ["b", "c", "a"]
        assert ranked[0].relevance == 1.0

    def test_large_sets_split_across_requests(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ts, "MAX_REQUEST_CHARS", 25)
        client = FakeClient({k: score(1.0) for k in "abc"})
        ranked = ts.rank("q", {"a": "x" * 10, "b": "y" * 10, "c": "z" * 10}, client=client)
        assert len(client.calls) == 2
        assert {r.id for r in ranked} == {"a", "b", "c"}
