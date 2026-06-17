from __future__ import annotations

import re
import threading
from dataclasses import dataclass
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


_lock = threading.RLock()
_transcripts: List[TranscriptTurn] = []
_exchanges: List[AIExchange] = []
_transcript_summary = ""
_exchange_summary = ""


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


def _looks_like_interviewer_question(text: str) -> bool:
    raw_text = str(text or "").strip()
    normalized = _normalize_question(raw_text)
    if not normalized:
        return False

    if "?" in raw_text:
        return True

    question_prefixes = (
        "what ",
        "why ",
        "how ",
        "when ",
        "where ",
        "which ",
        "who ",
        "can you ",
        "could you ",
        "would you ",
        "will you ",
        "do you ",
        "does ",
        "did ",
        "is ",
        "are ",
        "should ",
        "tell me ",
        "explain ",
        "describe ",
        "walk me ",
        "talk about ",
        "give me ",
        "show me ",
        "compare ",
        "design ",
        "solve ",
        "implement ",
        "optimize ",
        "debug ",
        "write ",
    )
    followup_prefixes = (
        "what about ",
        "how about ",
        "and if ",
        "and when ",
        "now ",
        "next ",
        "then ",
    )
    return normalized.startswith(question_prefixes + followup_prefixes)


def _recent_interviewer_questions(
    transcripts: List[TranscriptTurn],
    current_input: str,
    limit: int = 3,
) -> List[str]:
    question_groups: List[List[str]] = []
    active_group: Optional[List[str]] = None
    seen = set()
    previous_source = ""

    for turn in transcripts:
        if turn.source != "desktop":
            active_group = None
            previous_source = turn.source
            continue

        normalized = _normalize_question(turn.text)
        if not normalized or normalized in seen:
            previous_source = turn.source
            continue

        if _looks_like_interviewer_question(turn.text):
            active_group = [_compact(turn.text, 700)]
            question_groups.append(active_group)
            seen.add(normalized)
        elif active_group is not None and previous_source == "desktop":
            active_group.append(_compact(turn.text, 700))
            seen.add(normalized)
        previous_source = turn.source

    if current_input and _looks_like_interviewer_question(current_input):
        normalized = _normalize_question(current_input)
        if normalized not in seen:
            question_groups.append([_compact(current_input, 700)])
            seen.add(normalized)
    elif current_input and active_group is not None and transcripts and transcripts[-1].source == "desktop":
        normalized = _normalize_question(current_input)
        if normalized and normalized not in seen:
            active_group.append(_compact(current_input, 700))

    questions = [" ".join(group) for group in question_groups if group]
    return questions[-limit:]


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


def build_auto_answer_context(current_input: str, transcript_turns: int = 6, exchange_count: int = 2) -> str:
    current_input = str(current_input or "").strip()
    transcript_turns = max(0, int(transcript_turns or 0))
    exchange_count = max(0, int(exchange_count or 0))

    with _lock:
        transcripts = list(_transcripts[-transcript_turns:]) if transcript_turns else []
        exchanges = list(_exchanges[-exchange_count:]) if exchange_count else []

    interviewer_questions = _recent_interviewer_questions(transcripts, current_input)
    resume_relevance_text = "\n".join(interviewer_questions + [current_input])
    resume_section = get_resume_context_section() if is_resume_context_relevant(resume_relevance_text) else ""

    sections = [
        "Answer the most recent interviewer question or follow-up as a software engineering interview candidate.",
        (
            "Speaker labels matter: Interviewer turns are questions or follow-ups from desktop audio; "
            "Interviewee/Candidate turns are microphone transcriptions of what the candidate already said "
            "or asked to clarify."
        ),
        (
            "Use the recent transcript as one rolling exchange. If the latest interviewer question is split "
            "across multiple nearby Interviewer turns because of pauses, combine those turns before answering. "
            "If the Interviewee/Candidate asked a clarification and the Interviewer replied, use that reply "
            "to answer the clarified latest question. Do not answer the latest desktop transcript only because "
            "it is last; if it is a statement, use it as context for the recent interviewer question instead. "
            "Produce one answer only."
        ),
    ]

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

    if interviewer_questions:
        lines = [f"- {question}" for question in interviewer_questions]
        sections.append("Recent interviewer questions/follow-ups to answer:\n" + "\n".join(lines))

    if transcripts:
        lines = []
        for turn in transcripts:
            speaker = "Interviewer" if turn.source == "desktop" else "Interviewee/Candidate"
            lines.append(f"{turn.timestamp} {speaker}: {_compact(turn.text, 700)}")
        sections.append("Recent live transcript turns:\n" + "\n".join(lines))

    if current_input:
        sections.append(f"Latest desktop transcript (context, not automatically the question):\n{current_input}")

    return "\n\n".join(sections)


def clear_session_context() -> None:
    global _transcript_summary, _exchange_summary
    with _lock:
        _transcripts.clear()
        _exchanges.clear()
        _transcript_summary = ""
        _exchange_summary = ""


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
        }
