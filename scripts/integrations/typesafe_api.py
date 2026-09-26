"""
TypeSafe (Jev) Judgment Layer for Second Brain.

Fast, typed judgments — yes/no probabilities, one-of-N choices, graded scores —
that Ricky uses to decide, check, review, and rank before he delivers. Jev does
not write or explain; it returns calibrated answers that code and Ricky act on.

Usage:
    uv run python -m integrations.typesafe_api status
    uv run python -m integrations.typesafe_api decide --state-file notes.md \
        --question "Which option best fits the client's goal?" \
        --option "a=Rebuild the page" --option "b=Refresh the copy" --allow-none
    uv run python -m integrations.typesafe_api check --state-file source.md \
        --claim "Revenue grew 40% in Q2" --claim "The contract renews in March"
    uv run python -m integrations.typesafe_api review --state-file draft.md \
        --rubric deliverable --brief "One-page GBP audit for a plumber in Austin"
    uv run python -m integrations.typesafe_api rank --query "local SEO pricing" \
        --candidates-file sources.json
    uv run python -m integrations.typesafe_api ask --state-file ticket.json \
        --questions-file questions.json

Setup:
    1. Create an API key at https://console.typesafe.ai/keys
    2. Add to .env: TYPESAFE_API_KEY=your_key_here
    3. Test: cd .claude/scripts && uv run python -m integrations.typesafe_api status

Docs (source of truth for the API): https://docs.typesafe.ai/llms.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Add parent dir for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TYPESAFE_API_KEY, TYPESAFE_MODEL  # noqa: E402

RUBRICS_DIR = Path(__file__).resolve().parents[2] / "skills" / "typesafe" / "rubrics"

# Starting thresholds, not laws — tune them against real outcomes.
# A Choice/Score below CONFIDENCE_FLOOR is a split decision: look before acting.
CONFIDENCE_FLOOR = 0.8
# A Noul is P(yes). Between the two bounds the model is genuinely unsure.
NOUL_YES = 0.8
NOUL_NO = 0.2

# Jev 1.13: 64k tokens per request, 32k for state + the longest question.
# ~4 chars per token; stay under the limits with headroom.
MAX_STATE_CHARS = 100_000
MAX_REQUEST_CHARS = 200_000

NO_MATCH = "none_of_these"

RELEVANCE_LEVELS = [
    "Unrelated to the query",
    "Same general topic but does not help answer the query",
    "Partly answers the query or covers one aspect of it",
    "Directly and specifically answers the query",
]


class TypeSafeNotConfiguredError(RuntimeError):
    """TYPESAFE_API_KEY is not set."""


@dataclass
class Judgment:
    """One typed answer from the model."""

    id: str
    type: str  # "noul" | "choice" | "score"
    value: str | float
    confidence: float | None = None  # None for nouls — the probability is the signal
    probabilities: dict[str, float] = field(default_factory=dict)
    legend: dict[str, str] = field(default_factory=dict)  # score level → description

    @property
    def uncertain(self) -> bool:
        """True when this answer should be looked at before anyone acts on it."""
        if self.type == "noul":
            return NOUL_NO < float(self.value) < NOUL_YES
        return self.confidence is not None and self.confidence < CONFIDENCE_FLOOR


@dataclass
class JudgmentSet:
    """All answers from one request."""

    answers: dict[str, Judgment]
    model: str
    input_tokens: int = 0

    def __getitem__(self, question_id: str) -> Judgment:
        return self.answers[question_id]


@dataclass
class ClaimVerdict:
    """How a claim stands against the evidence."""

    claim: str
    verdict: str  # "supported" | "contradicted" | "not_addressed" | "fabricated_quote"
    confidence: float
    needs_review: bool


@dataclass
class Review:
    """A rubric review: weighted composite, blockers, and what to fix."""

    rubric: str
    verdict: str  # "pass" | "revise" | "check"
    score: float  # 0-100
    pass_score: float
    dimensions: dict[str, dict[str, Any]]
    blockers: dict[str, dict[str, Any]]
    skipped: list[str]


@dataclass
class Ranked:
    """One candidate's relevance to a query."""

    id: str
    relevance: float  # 0-1
    confidence: float


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def is_configured() -> bool:
    return bool(TYPESAFE_API_KEY)


def get_client() -> Any:
    """Return an authenticated TypeSafe client."""
    if not TYPESAFE_API_KEY:
        raise TypeSafeNotConfiguredError(
            "TYPESAFE_API_KEY not set. Add it to .claude/scripts/.env "
            "(create one at https://console.typesafe.ai/keys)."
        )
    from typesafe_sdk import TypeSafeClient

    return TypeSafeClient(api_key=TYPESAFE_API_KEY, model=TYPESAFE_MODEL)


def build_question(spec: Mapping[str, Any]) -> Any:
    """Turn a JSON question spec ({"type", "instructions", "criteria"}) into an SDK question."""
    from typesafe_sdk import Choice, Noul, Score

    kind = spec.get("type")
    instructions = spec.get("instructions")
    criteria = spec.get("criteria")
    if not instructions:
        raise ValueError(f"question needs 'instructions': {dict(spec)!r}")

    if kind == "noul":
        if criteria is None:
            return Noul(instructions=instructions)
        return Noul(instructions=instructions, criteria=criteria)
    if kind == "choice":
        if not isinstance(criteria, Mapping) or len(criteria) < 2:
            raise ValueError("a choice needs 'criteria': a map of at least 2 options")
        return Choice(instructions=instructions, criteria=criteria)
    if kind == "score":
        if isinstance(criteria, (str, bytes)) or not isinstance(criteria, Sequence):
            raise ValueError("a score needs 'criteria': an ordered list of levels")
        if not 2 <= len(criteria) <= 10:
            raise ValueError("a score needs between 2 and 10 levels")
        return Score(instructions=instructions, criteria=list(criteria))
    raise ValueError(f"unknown question type {kind!r} — use noul, choice, or score")


def _to_judgment(question_id: str, answer: Any) -> Judgment:
    if answer.type == "noul":
        return Judgment(id=question_id, type="noul", value=float(answer.noul))
    if answer.type == "choice":
        return Judgment(
            id=question_id,
            type="choice",
            value=str(answer.choice),
            confidence=float(answer.confidence),
            probabilities={str(k): float(v) for k, v in answer.probabilities.items()},
        )
    return Judgment(
        id=question_id,
        type="score",
        value=float(answer.score),
        confidence=float(answer.confidence),
        probabilities={str(k): float(v) for k, v in answer.probabilities.items()},
        legend={str(k): _as_text(v) for k, v in answer.legend.items()},
    )


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _size(value: Any) -> int:
    return len(_as_text(value))


def ask(
    state: Any,
    questions: Mapping[str, Any],
    *,
    client: Any = None,
) -> JudgmentSet:
    """
    Ask independent questions about the same state in one request.

    Args:
        state: Text, or a JSON object/array with named fields the questions
            can reference in backticks (e.g. `ticket.messages[0].text`).
        questions: Question id → spec dict or SDK question. Ids are for code
            only; the model never sees them, so put the full meaning in
            `instructions`.
    """
    if not questions:
        raise ValueError("no questions to ask")
    if _size(state) > MAX_STATE_CHARS:
        raise ValueError(
            f"state is ~{_size(state) // 4:,} tokens; Jev reads about 32k per request. "
            "Split it and judge each part, or send only the relevant section."
        )
    built = {
        qid: build_question(spec) if isinstance(spec, Mapping) else spec
        for qid, spec in questions.items()
    }
    response = (client or get_client()).system_one(state, built)
    return JudgmentSet(
        answers={qid: _to_judgment(qid, ans) for qid, ans in response.answers.items()},
        model=response.model,
        input_tokens=response.usage.input_tokens or 0,
    )


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------


def decide(
    state: Any,
    question: str,
    options: Mapping[str, str | None],
    *,
    allow_none: bool = False,
    client: Any = None,
) -> Judgment:
    """
    Pick one option from a defined set.

    Set allow_none when it's possible that nothing fits — otherwise the model
    must pick something even from a bad list.
    """
    criteria: dict[str, str | None] = dict(options)
    if allow_none:
        criteria[NO_MATCH] = "None of the other options fits"
    spec = {"type": "choice", "instructions": question, "criteria": criteria}
    return ask(state, {"decision": spec}, client=client)["decision"]


def _normalize(text: str) -> str:
    """Collapse whitespace and fold curly quotes so a quote matches across line wraps."""
    table = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
    return re.sub(r"\s+", " ", text.translate(table)).strip().lower()


def check(
    evidence: str,
    claims: Sequence[str | Mapping[str, str]],
    *,
    client: Any = None,
) -> list[ClaimVerdict]:
    """
    Check each claim against the evidence it's supposed to rest on.

    A claim may be a string, or {"claim": ..., "quote": ...}. Quotes are matched
    verbatim in code first — a quote that isn't in the evidence is fabricated,
    no model needed. Everything else gets one Choice per claim.
    """
    verdicts: dict[int, ClaimVerdict] = {}
    questions: dict[str, Any] = {}
    haystack = _normalize(evidence)

    for i, raw in enumerate(claims):
        claim = raw if isinstance(raw, str) else raw["claim"]
        quote = None if isinstance(raw, str) else raw.get("quote")
        if quote and _normalize(quote) not in haystack:
            verdicts[i] = ClaimVerdict(claim, "fabricated_quote", 1.0, needs_review=True)
            continue
        questions[str(i)] = {
            "type": "choice",
            "instructions": {
                "claim": claim,
                "question": "How does `evidence` relate to `claim`?",
            },
            "criteria": {
                "supported": "The evidence states or clearly implies the claim",
                "contradicted": "The evidence says something that conflicts with the claim",
                "not_addressed": (
                    "The evidence does not say enough to confirm or deny the claim, "
                    "including when it covers the topic but not this specific point"
                ),
            },
        }

    if questions:
        result = ask({"evidence": evidence}, questions, client=client)
        for qid, judgment in result.answers.items():
            i = int(qid)
            raw = claims[i]
            verdicts[i] = ClaimVerdict(
                claim=raw if isinstance(raw, str) else raw["claim"],
                verdict=str(judgment.value),
                confidence=judgment.confidence or 0.0,
                needs_review=judgment.uncertain or judgment.value != "supported",
            )
    return [verdicts[i] for i in range(len(claims))]


def load_rubric(name_or_path: str) -> dict[str, Any]:
    """Load a rubric by name from skills/typesafe/rubrics/, or from a JSON file path."""
    path = Path(name_or_path)
    if not path.suffix:
        path = RUBRICS_DIR / f"{name_or_path}.json"
    if not path.exists():
        available = ", ".join(list_rubrics()) or "none"
        raise FileNotFoundError(f"no rubric {name_or_path!r} (available: {available})")
    rubric: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    rubric.setdefault("name", path.stem)
    return rubric


def list_rubrics() -> list[str]:
    if not RUBRICS_DIR.exists():
        return []
    return sorted(p.stem for p in RUBRICS_DIR.glob("*.json"))


def review(
    deliverable: str,
    rubric: str | Mapping[str, Any] = "deliverable",
    *,
    brief: str | None = None,
    client: Any = None,
) -> Review:
    """
    Review a deliverable against a rubric before it ships.

    Dimensions are graded Scores combined with weights — strengths can offset
    weaknesses. Blockers are separate yes/no conditions — any one of them fails
    the review no matter how good the rest is.
    """
    spec = load_rubric(rubric) if isinstance(rubric, str) else dict(rubric)
    state = {"brief": brief or "", "deliverable": deliverable}

    questions: dict[str, Any] = {}
    skipped: list[str] = []
    for kind, prefix in (("dimensions", "d:"), ("blockers", "b:")):
        for key, item in spec.get(kind, {}).items():
            if item.get("requires_brief") and not brief:
                skipped.append(key)
                continue
            if kind == "dimensions":
                question = {"type": "score", "criteria": item["levels"]}
            else:
                question = {"type": "noul", "criteria": item.get("criteria")}
            questions[prefix + key] = {**question, "instructions": item["instructions"]}

    result = ask(state, questions, client=client)

    dimensions: dict[str, dict[str, Any]] = {}
    weighted = total_weight = 0.0
    for key, item in spec.get("dimensions", {}).items():
        if key in skipped:
            continue
        judgment = result["d:" + key]
        top = len(item["levels"]) - 1
        normalized = float(judgment.value) / top
        weight = float(item.get("weight", 1))
        weighted += normalized * weight
        total_weight += weight
        nearest = min(top, round(float(judgment.value)))
        dimensions[key] = {
            "score": round(normalized * 100),
            "weight": weight,
            "level": item["levels"][nearest],
            "next_level": item["levels"][min(top, nearest + 1)],
            "confidence": judgment.confidence,
        }

    blockers: dict[str, dict[str, Any]] = {}
    for key in spec.get("blockers", {}):
        if key in skipped:
            continue
        probability = float(result["b:" + key].value)
        status = (
            "triggered" if probability >= NOUL_YES
            else "clear" if probability <= NOUL_NO
            else "unsure"
        )
        blockers[key] = {"probability": round(probability, 2), "status": status}

    score = round(100 * weighted / total_weight, 1) if total_weight else 0.0
    pass_score = float(spec.get("pass_score", 75))
    statuses = {b["status"] for b in blockers.values()}
    if "triggered" in statuses or score < pass_score:
        verdict = "revise"
    elif "unsure" in statuses:
        verdict = "check"
    else:
        verdict = "pass"

    return Review(
        rubric=str(spec.get("name", "custom")),
        verdict=verdict,
        score=score,
        pass_score=pass_score,
        dimensions=dimensions,
        blockers=blockers,
        skipped=skipped,
    )


def rank(
    query: str,
    candidates: Mapping[str, str],
    *,
    client: Any = None,
) -> list[Ranked]:
    """
    Rank candidates (sources, passages, ideas, leads) by relevance to a query.

    Each candidate gets its own comparable Score, so results from separate
    requests sort together. Large sets are split across requests automatically.
    """
    batches: list[dict[str, str]] = [{}]
    used = 0
    for cid, text in candidates.items():
        if len(text) > MAX_STATE_CHARS:
            raise ValueError(f"candidate {cid!r} is too long to judge in one request; trim it")
        if batches[-1] and used + len(text) > MAX_REQUEST_CHARS:
            batches.append({})
            used = 0
        batches[-1][cid] = text
        used += len(text)

    ranked: list[Ranked] = []
    top = len(RELEVANCE_LEVELS) - 1
    for batch in batches:
        if not batch:
            continue
        questions = {
            cid: {
                "type": "score",
                "instructions": {
                    "candidate": text,
                    "question": "How well does `candidate` answer `query`?",
                },
                "criteria": RELEVANCE_LEVELS,
            }
            for cid, text in batch.items()
        }
        result = ask({"query": query}, questions, client=client)
        for cid, judgment in result.answers.items():
            ranked.append(
                Ranked(cid, round(float(judgment.value) / top, 3), judgment.confidence or 0.0)
            )
    return sorted(ranked, key=lambda r: r.relevance, reverse=True)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_judgment(judgment: Judgment) -> str:
    flag = "  ⚠ uncertain — verify before acting" if judgment.uncertain else ""
    if judgment.type == "noul":
        return f"{judgment.id}: P(yes) = {float(judgment.value):.2f}{flag}"
    spread = ", ".join(
        f"{k} {v:.2f}" for k, v in sorted(judgment.probabilities.items(), key=lambda kv: -kv[1])
        if v >= 0.01
    )
    if judgment.type == "choice":
        return (
            f"{judgment.id}: {judgment.value} "
            f"(confidence {judgment.confidence:.2f}; {spread}){flag}"
        )
    level = judgment.legend.get(str(round(float(judgment.value))), "")
    return (
        f"{judgment.id}: {float(judgment.value):.2f} — nearest level: {level} "
        f"(confidence {judgment.confidence:.2f}){flag}"
    )


def format_answers_for_context(result: JudgmentSet) -> str:
    lines = [format_judgment(j) for j in result.answers.values()]
    lines.append(f"[{result.model}, {result.input_tokens:,} input tokens]")
    return "\n".join(lines)


def format_verdicts_for_context(verdicts: Sequence[ClaimVerdict]) -> str:
    marks = {"supported": "✓", "contradicted": "✗", "not_addressed": "?", "fabricated_quote": "✗"}
    lines = []
    for v in verdicts:
        flag = "  ⚠ review" if v.needs_review else ""
        lines.append(
            f"{marks.get(v.verdict, '?')} {v.verdict} ({v.confidence:.2f}){flag} — {v.claim}"
        )
    solid = sum(1 for v in verdicts if not v.needs_review)
    lines.append(f"{solid}/{len(verdicts)} claims supported with confidence")
    return "\n".join(lines)


def format_review_for_context(result: Review) -> str:
    lines = [
        f"VERDICT: {result.verdict.upper()} — {result.score:.0f}/100 "
        f"(pass ≥ {result.pass_score:.0f}, rubric: {result.rubric})"
    ]
    for key, b in result.blockers.items():
        if b["status"] != "clear":
            lines.append(f"  BLOCKER {b['status']}: {key} (P={b['probability']:.2f})")
    for key, d in sorted(result.dimensions.items(), key=lambda kv: kv[1]["score"]):
        lines.append(f"  {d['score']:>3}  {key} (×{d['weight']:g}) — {d['level']}")
        if d["score"] < 100 and d["next_level"] != d["level"]:
            lines.append(f"       to improve → {d['next_level']}")
    if result.skipped:
        lines.append(f"  skipped (no --brief given): {', '.join(result.skipped)}")
    return "\n".join(lines)


def format_ranking_for_context(ranked: Sequence[Ranked]) -> str:
    return "\n".join(
        f"{i:>2}. {r.relevance:.2f}  {r.id}" + ("  ⚠ uncertain" if r.confidence < 0.5 else "")
        for i, r in enumerate(ranked, 1)
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _read_state(args: argparse.Namespace) -> Any:
    """State from --state, --state-file (.json is parsed), or stdin."""
    if args.state is not None:
        return args.state
    if args.state_file:
        text = Path(args.state_file).read_text(encoding="utf-8")
        return json.loads(text) if args.state_file.endswith(".json") else text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    print("Error: give --state, --state-file, or pipe text on stdin")
    sys.exit(1)


def _parse_options(pairs: Sequence[str]) -> dict[str, str | None]:
    options: dict[str, str | None] = {}
    for pair in pairs:
        key, _, description = pair.partition("=")
        options[key.strip()] = description.strip() or None
    return options


def _emit(payload: Any, text: str, as_json: bool) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=asdict) if as_json else text)


def main() -> None:
    parser = argparse.ArgumentParser(description="TypeSafe judgment layer")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_state(p: argparse.ArgumentParser) -> None:
        p.add_argument("--state", default=None, help="Inline text to judge")
        p.add_argument("--state-file", default=None, help="File to judge (.json is parsed)")
        p.add_argument("--json", action="store_true", help="Full JSON output")

    sub.add_parser("status", help="Check the key and list models")
    sub.add_parser("rubrics", help="List review rubrics")

    p_ask = sub.add_parser("ask", help="Ask raw questions")
    add_state(p_ask)
    p_ask.add_argument("--questions", default=None, help="JSON map of question id → spec")
    p_ask.add_argument("--questions-file", default=None)

    p_decide = sub.add_parser("decide", help="Pick one option")
    add_state(p_decide)
    p_decide.add_argument("--question", required=True)
    p_decide.add_argument("--option", action="append", default=[], metavar="KEY=DESCRIPTION")
    p_decide.add_argument("--allow-none", action="store_true", help="Let nothing fit")

    p_check = sub.add_parser("check", help="Check claims against evidence")
    add_state(p_check)
    p_check.add_argument("--claim", action="append", default=[])
    p_check.add_argument("--claims-file", default=None, help="JSON list of claims")

    p_review = sub.add_parser("review", help="Review a deliverable against a rubric")
    add_state(p_review)
    p_review.add_argument("--rubric", default="deliverable", help="Rubric name or JSON path")
    p_review.add_argument("--brief", default=None, help="What was asked for")
    p_review.add_argument("--brief-file", default=None)

    p_rank = sub.add_parser("rank", help="Rank candidates by relevance to a query")
    p_rank.add_argument("--query", required=True)
    p_rank.add_argument("--candidates-file", required=True, help="JSON map of id → text")
    p_rank.add_argument("--json", action="store_true")

    args = parser.parse_args()

    try:
        if args.command == "status":
            if not is_configured():
                print("TypeSafe: NOT configured — TYPESAFE_API_KEY is not set")
                sys.exit(1)
            names = [m.name for m in get_client().models.list().models]
            print(f"TypeSafe: OK — model {TYPESAFE_MODEL} (available: {', '.join(names)})")

        elif args.command == "rubrics":
            for name in list_rubrics():
                print(f"{name}: {load_rubric(name).get('description', '')}")

        elif args.command == "ask":
            raw = args.questions or Path(args.questions_file).read_text(encoding="utf-8")
            result = ask(_read_state(args), json.loads(raw))
            _emit(result, format_answers_for_context(result), args.json)

        elif args.command == "decide":
            if len(args.option) < 2:
                print("Error: give at least two --option KEY=DESCRIPTION")
                sys.exit(1)
            judgment = decide(
                _read_state(args), args.question, _parse_options(args.option),
                allow_none=args.allow_none,
            )
            _emit(judgment, format_judgment(judgment), args.json)

        elif args.command == "check":
            claims: list[Any] = list(args.claim)
            if args.claims_file:
                claims += json.loads(Path(args.claims_file).read_text(encoding="utf-8"))
            if not claims:
                print("Error: give --claim or --claims-file")
                sys.exit(1)
            verdicts = check(_as_text(_read_state(args)), claims)
            _emit(verdicts, format_verdicts_for_context(verdicts), args.json)

        elif args.command == "review":
            brief = args.brief
            if args.brief_file:
                brief = Path(args.brief_file).read_text(encoding="utf-8")
            outcome = review(_as_text(_read_state(args)), args.rubric, brief=brief)
            _emit(outcome, format_review_for_context(outcome), args.json)

        elif args.command == "rank":
            candidates = json.loads(Path(args.candidates_file).read_text(encoding="utf-8"))
            ranked = rank(args.query, candidates)
            _emit(ranked, format_ranking_for_context(ranked), args.json)

    except (TypeSafeNotConfiguredError, FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
