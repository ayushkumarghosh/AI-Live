from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from resume_context import get_resume_context_section, is_resume_context_relevant


MAX_TRANSCRIPT_TURNS = 12
MAX_AI_EXCHANGES = 8
MAX_SUMMARY_CHARS = 6000
MAX_FIELD_CHARS = 1200


@dataclass
class TranscriptTurn:
    source: str
    text: str
    timestamp: str


@dataclass
class AIExchange:
    mode: str
    user_content: str
    response: str
    user_query: str
    timestamp: str
    current_input: str = ""


@dataclass
class AutoAnswerSegmentState:
    segment_id: int = 0
    interviewer_turns: List[str] = field(default_factory=list)
    last_answer: str = ""
    last_turn_at: float = 0.0
    last_target_summary: str = ""


_lock = threading.RLock()
_transcripts: List[TranscriptTurn] = []
_exchanges: List[AIExchange] = []
_transcript_summary = ""
_exchange_summary = ""
_auto_answer_segment = AutoAnswerSegmentState()


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _compact(text: str, limit: int = MAX_FIELD_CHARS) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _normalize_question(text: str) -> str:
    text = str(text or "").casefold()
    text = re.sub(r"[^a-z0-9_]+", " ", text)
    return " ".join(text.split())


def _latest_interviewer_turns(
    transcripts: List[TranscriptTurn],
    current_input: str,
    limit: int = 5,
) -> List[str]:
    limit = max(0, int(limit or 0))
    if limit <= 0:
        return []

    turns = []
    for turn in transcripts:
        if turn.source != "desktop":
            continue
        text = _compact(turn.text, 700)
        if text:
            turns.append(text)

    current_input = str(current_input or "").strip()
    current_normalized = _normalize_question(current_input)
    last_desktop_normalized = _normalize_question(turns[-1]) if turns else ""
    if current_normalized and current_normalized != last_desktop_normalized:
        turns.append(_compact(current_input, 700))

    return turns[-limit:]


def _format_auto_answer_target(interviewer_turns: List[str]) -> str:
    lines = [f"{idx}. {turn}" for idx, turn in enumerate(interviewer_turns, start=1)]
    return (
        "Interviewer turns to answer together in the single visible response:\n"
        + "\n".join(lines)
    )


def _token_set(text: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "why",
        "with",
        "would",
        "you",
    }
    return {token for token in _normalize_question(text).split() if token not in stopwords}


def _topic_overlap(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), 1)


def _looks_like_hard_segment_reset(text: str) -> bool:
    normalized = f" {_normalize_question(text)} "
    reset_phrases = (
        " next question ",
        " new question ",
        " new problem ",
        " next problem ",
        " lets move on ",
        " let us move on ",
        " move on ",
        " switch topics ",
        " different question ",
    )
    return any(phrase in normalized for phrase in reset_phrases)


def _append_unique_turn(turns: List[str], text: str) -> List[str]:
    text = _compact(text, 700)
    if not text:
        return list(turns)

    normalized = _normalize_question(text)
    if not normalized:
        return list(turns)
    if turns and _normalize_question(turns[-1]) == normalized:
        return list(turns)
    return [*turns, text]


def _looks_like_same_question(left: str, right: str) -> bool:
    left_normalized = _normalize_question(left)
    right_normalized = _normalize_question(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True

    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    if left_tokens and left_tokens == right_tokens:
        return True

    shorter = min(len(left_normalized), len(right_normalized))
    if shorter < 30:
        return False

    ratio = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return ratio >= 0.93 and overlap >= 0.85


def _trim_summary(text: str) -> str:
    if len(text) <= MAX_SUMMARY_CHARS:
        return text
    return text[-MAX_SUMMARY_CHARS:].lstrip()


def _append_transcript_summary(lines: List[str]) -> None:
    global _transcript_summary
    if not lines:
        return

    addition = "\n".join(lines)
    if _transcript_summary:
        _transcript_summary = f"{_transcript_summary}\n{addition}"
    else:
        _transcript_summary = addition
    _transcript_summary = _trim_summary(_transcript_summary)


def _append_exchange_summary(lines: List[str]) -> None:
    global _exchange_summary
    if not lines:
        return

    addition = "\n".join(lines)
    if _exchange_summary:
        _exchange_summary = f"{_exchange_summary}\n{addition}"
    else:
        _exchange_summary = addition
    _exchange_summary = _trim_summary(_exchange_summary)


def _summarize_transcript(turn: TranscriptTurn) -> str:
    speaker = "Interviewer" if turn.source == "desktop" else "Me"
    return f"- {turn.timestamp} transcript {speaker}: {_compact(turn.text, 500)}"


def _summarize_exchange(exchange: AIExchange) -> str:
    return (
        f"- {exchange.timestamp} {exchange.mode} exchange: "
        f"request={_compact(exchange.user_query or exchange.current_input or exchange.user_content, 450)}; "
        f"answer={_compact(exchange.response, 650)}"
    )


def _prune_locked() -> None:
    transcript_lines = []
    exchange_lines = []

    while len(_transcripts) > MAX_TRANSCRIPT_TURNS:
        transcript_lines.append(_summarize_transcript(_transcripts.pop(0)))

    while len(_exchanges) > MAX_AI_EXCHANGES:
        exchange_lines.append(_summarize_exchange(_exchanges.pop(0)))

    _append_transcript_summary(transcript_lines)
    _append_exchange_summary(exchange_lines)


def record_transcript(text: str, source: str) -> None:
    text = str(text or "").strip()
    if not text:
        return

    normalized_source = "desktop" if source == "desktop" else "mic"
    with _lock:
        _transcripts.append(
            TranscriptTurn(
                source=normalized_source,
                text=text,
                timestamp=_timestamp(),
            )
        )
        _prune_locked()


def record_exchange(
    user_content: str,
    assistant_response: Dict[str, str],
    mode: str,
    current_input: str = "",
) -> None:
    response = str((assistant_response or {}).get("response", "")).strip()
    user_query = str((assistant_response or {}).get("user_query", "")).strip()
    user_content = str(user_content or "").strip()
    current_input = str(current_input or user_query).strip()
    if not user_content and not user_query and not response:
        return

    with _lock:
        _exchanges.append(
            AIExchange(
                mode=str(mode or "analysis"),
                user_content=user_content,
                response=response,
                user_query=user_query,
                timestamp=_timestamp(),
                current_input=current_input,
            )
        )
        _prune_locked()


def find_repeated_exchange(current_input: str, mode: str) -> Optional[Dict[str, str]]:
    current_input = str(current_input or "").strip()
    if not current_input:
        return None

    mode = str(mode or "analysis")
    with _lock:
        exchanges = list(_exchanges)

    for exchange in reversed(exchanges):
        if exchange.mode != mode:
            continue
        previous_input = exchange.current_input or exchange.user_query
        if _looks_like_same_question(current_input, previous_input):
            return {
                "mode": exchange.mode,
                "current_input": exchange.current_input,
                "user_query": exchange.user_query,
                "response": exchange.response,
                "timestamp": exchange.timestamp,
            }
    return None


def build_context(current_input: str, mode: str, include_transcripts: bool = True) -> str:
    current_input = str(current_input or "").strip()
    mode = str(mode or "analysis")

    with _lock:
        transcript_summary = _transcript_summary if include_transcripts else ""
        exchange_summary = _exchange_summary
        transcripts = list(_transcripts) if include_transcripts else []
        exchanges = list(_exchanges)

    sections = [
        "Session context for this software engineering interview.",
        f"Current analysis mode: {mode}.",
    ]

    if mode == "general":
        resume_relevance_text = "\n".join([current_input] + [turn.text for turn in transcripts])
        resume_section = get_resume_context_section() if is_resume_context_relevant(resume_relevance_text) else ""
        if resume_section:
            sections.append(resume_section)

    summary_parts = []
    if exchange_summary:
        summary_parts.append("Earlier AI exchanges:\n" + exchange_summary)
    if transcript_summary:
        summary_parts.append("Earlier transcript turns:\n" + transcript_summary)
    if summary_parts:
        sections.append("Rolling summary of earlier context:\n" + "\n\n".join(summary_parts))

    if exchanges:
        lines = []
        for idx, exchange in enumerate(exchanges, start=1):
            lines.append(
                f"Previous AI exchange {idx} ({exchange.mode}, {exchange.timestamp})\n"
                f"Request: {_compact(exchange.user_query or exchange.current_input or exchange.user_content)}\n"
                f"Answer: {_compact(exchange.response)}"
            )
        sections.append("Recent AI exchanges:\n" + "\n\n".join(lines))

    if transcripts:
        lines = []
        for turn in transcripts:
            speaker = "Interviewer" if turn.source == "desktop" else "Me"
            lines.append(f"{turn.timestamp} {speaker}: {turn.text}")
        sections.append("Recent live transcript turns:\n" + "\n".join(lines))

    if current_input:
        sections.append(f"Current selected text or user request:\n{current_input}")
    else:
        sections.append(
            "No current text was provided. Use the recent transcript turns and screenshots when available."
        )

    return "\n\n".join(sections)


def _compose_auto_answer_context(
    current_input: str,
    transcripts: List[TranscriptTurn],
    exchanges: List[AIExchange],
    interviewer_turns: List[str],
    previous_answer: str = "",
) -> tuple[str, str]:
    current_input = str(current_input or "").strip()
    target_section = _format_auto_answer_target(interviewer_turns) if interviewer_turns else ""
    target_summary = target_section or f"Latest desktop transcript:\n{current_input}"
    resume_relevance_text = "\n".join(interviewer_turns + [current_input])
    resume_section = get_resume_context_section() if is_resume_context_relevant(resume_relevance_text) else ""

    sections = [
        (
            "Answer the interviewer turns in the target section as one self-contained "
            "software engineering interview answer."
        ),
        (
            "Speaker labels matter: Interviewer turns are questions or follow-ups from desktop audio; "
            "Interviewee/Candidate turns are microphone transcriptions of what the candidate already said "
            "or asked to clarify."
        ),
        (
            "Use the recent transcript as one rolling exchange. If the latest interviewer question is split "
            "across multiple nearby Interviewer turns because of pauses, combine those turns before answering. "
            "If the Interviewee/Candidate asked a clarification and the Interviewer replied, use that reply "
            "to answer the clarified latest question. Interviewer statements, confirmations, or constraints "
            "in the target section must be folded into the same answer instead of ignored. Only the latest "
            "auto-answer is visible to the candidate, so produce one complete answer only."
        ),
    ]

    if target_section:
        sections.append(target_section)

    previous_answer = str(previous_answer or "").strip()
    if previous_answer:
        sections.append(
            "Previous visible auto-answer to update for this same conversation segment:\n"
            + _compact(previous_answer, 1400)
        )

    if resume_section:
        sections.append(resume_section)

    if exchanges:
        lines = []
        for idx, exchange in enumerate(exchanges, start=1):
            lines.append(
                f"Prior answer {idx} ({exchange.mode}, {exchange.timestamp})\n"
                f"Question: {_compact(exchange.user_query or exchange.current_input or exchange.user_content, 350)}\n"
                f"Answer: {_compact(exchange.response, 450)}"
            )
        sections.append("Recent answer context:\n" + "\n\n".join(lines))

    if transcripts:
        lines = []
        for turn in transcripts:
            speaker = "Interviewer" if turn.source == "desktop" else "Interviewee/Candidate"
            lines.append(f"{turn.timestamp} {speaker}: {_compact(turn.text, 700)}")
        sections.append("Recent live transcript turns:\n" + "\n".join(lines))

    if current_input:
        sections.append(f"Latest desktop transcript (context, not automatically the question):\n{current_input}")

    return "\n\n".join(sections), target_summary


def build_auto_answer_context_bundle(
    current_input: str,
    transcript_turns: int = 6,
    exchange_count: int = 2,
    target_interviewer_turns: int = 5,
) -> tuple[str, str]:
    current_input = str(current_input or "").strip()
    transcript_turns = max(0, int(transcript_turns or 0))
    exchange_count = max(0, int(exchange_count or 0))
    target_interviewer_turns = max(0, int(target_interviewer_turns or 0))

    with _lock:
        all_transcripts = list(_transcripts)
        transcripts = list(_transcripts[-transcript_turns:]) if transcript_turns else []
        exchanges = list(_exchanges[-exchange_count:]) if exchange_count else []

    interviewer_turns = _latest_interviewer_turns(
        all_transcripts,
        current_input,
        target_interviewer_turns,
    )
    return _compose_auto_answer_context(
        current_input,
        transcripts,
        exchanges,
        interviewer_turns,
    )


def prepare_auto_answer_turn(
    current_input: str,
    transcript_turns: int = 6,
    exchange_count: int = 2,
    target_interviewer_turns: int = 5,
    segment_gap_seconds: float = 45.0,
    topic_overlap_min: float = 0.18,
    previous_answer: Optional[str] = None,
    now: Optional[float] = None,
) -> Dict[str, object]:
    current_input = str(current_input or "").strip()
    transcript_turns = max(0, int(transcript_turns or 0))
    exchange_count = max(0, int(exchange_count or 0))
    target_interviewer_turns = max(0, int(target_interviewer_turns or 0))
    segment_gap_seconds = max(0.0, float(segment_gap_seconds or 0.0))
    topic_overlap_min = max(0.0, float(topic_overlap_min or 0.0))
    now = time.time() if now is None else float(now)

    with _lock:
        active = AutoAnswerSegmentState(
            segment_id=_auto_answer_segment.segment_id,
            interviewer_turns=list(_auto_answer_segment.interviewer_turns),
            last_answer=_auto_answer_segment.last_answer,
            last_turn_at=_auto_answer_segment.last_turn_at,
            last_target_summary=_auto_answer_segment.last_target_summary,
        )
        all_transcripts = list(_transcripts)
        transcripts = list(_transcripts[-transcript_turns:]) if transcript_turns else []
        exchanges = list(_exchanges[-exchange_count:]) if exchange_count else []

    previous_visible_answer = (
        str(previous_answer)
        if previous_answer is not None
        else str(active.last_answer or "")
    )
    has_active_segment = bool(active.interviewer_turns or active.last_answer)
    segment_text = " ".join(active.interviewer_turns)
    hard_reset = _looks_like_hard_segment_reset(current_input)
    gap_elapsed = bool(
        has_active_segment
        and active.last_turn_at
        and now - active.last_turn_at >= segment_gap_seconds
    )
    overlap = _topic_overlap(current_input, segment_text) if segment_text else 0.0
    low_overlap = overlap < topic_overlap_min
    starts_new_segment = (
        not has_active_segment
        or hard_reset
        or (gap_elapsed and low_overlap)
    )

    if starts_new_segment:
        segment_id = active.segment_id + 1
        if has_active_segment:
            target_turns = _append_unique_turn([], current_input)[-target_interviewer_turns:]
        else:
            target_turns = _latest_interviewer_turns(
                all_transcripts,
                current_input,
                target_interviewer_turns,
            ) or _append_unique_turn([], current_input)
        context_previous_answer = ""
    else:
        segment_id = active.segment_id or 1
        target_turns = _append_unique_turn(active.interviewer_turns, current_input)[-target_interviewer_turns:]
        context_previous_answer = previous_visible_answer

    context_text, target_summary = _compose_auto_answer_context(
        current_input,
        transcripts,
        exchanges,
        target_turns,
        previous_answer=context_previous_answer,
    )

    return {
        "context_text": context_text,
        "target_summary": target_summary,
        "segment_id": segment_id,
        "starts_new_segment": starts_new_segment,
        "should_clear_previous_answer": bool(starts_new_segment and previous_visible_answer.strip()),
        "previous_answer": previous_visible_answer,
        "target_turns": target_turns,
        "created_at": now,
        "hard_reset": hard_reset,
        "gap_elapsed": gap_elapsed,
        "topic_overlap": overlap,
    }


def commit_auto_answer_turn(turn_context: Dict[str, object], answer: str, now: Optional[float] = None) -> None:
    answer = str(answer or "")
    if not turn_context or not answer.strip():
        return

    now = time.time() if now is None else float(now)
    with _lock:
        _auto_answer_segment.segment_id = int(turn_context.get("segment_id") or 0)
        _auto_answer_segment.interviewer_turns = list(turn_context.get("target_turns") or [])
        _auto_answer_segment.last_answer = answer
        _auto_answer_segment.last_turn_at = now
        _auto_answer_segment.last_target_summary = str(turn_context.get("target_summary") or "")


def build_auto_answer_context(
    current_input: str,
    transcript_turns: int = 6,
    exchange_count: int = 2,
    target_interviewer_turns: int = 5,
) -> str:
    context_text, _target_summary = build_auto_answer_context_bundle(
        current_input,
        transcript_turns=transcript_turns,
        exchange_count=exchange_count,
        target_interviewer_turns=target_interviewer_turns,
    )
    return context_text


def clear_session_context() -> None:
    global _transcript_summary, _exchange_summary
    with _lock:
        _transcripts.clear()
        _exchanges.clear()
        _transcript_summary = ""
        _exchange_summary = ""
        _auto_answer_segment.segment_id = 0
        _auto_answer_segment.interviewer_turns.clear()
        _auto_answer_segment.last_answer = ""
        _auto_answer_segment.last_turn_at = 0.0
        _auto_answer_segment.last_target_summary = ""


def clear_transcript_context() -> None:
    global _transcript_summary
    with _lock:
        _transcripts.clear()
        _transcript_summary = ""


def snapshot() -> Dict[str, object]:
    with _lock:
        summary_parts = []
        if _exchange_summary:
            summary_parts.append(_exchange_summary)
        if _transcript_summary:
            summary_parts.append(_transcript_summary)
        return {
            "summary": "\n".join(summary_parts),
            "transcript_summary": _transcript_summary,
            "exchange_summary": _exchange_summary,
            "transcripts": [turn.__dict__.copy() for turn in _transcripts],
            "exchanges": [exchange.__dict__.copy() for exchange in _exchanges],
            "auto_answer_segment": {
                "segment_id": _auto_answer_segment.segment_id,
                "interviewer_turns": list(_auto_answer_segment.interviewer_turns),
                "last_answer": _auto_answer_segment.last_answer,
                "last_turn_at": _auto_answer_segment.last_turn_at,
                "last_target_summary": _auto_answer_segment.last_target_summary,
            },
        }
