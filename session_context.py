from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


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
        f"request={_compact(exchange.user_query or exchange.user_content, 450)}; "
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


def record_exchange(user_content: str, assistant_response: Dict[str, str], mode: str) -> None:
    response = str((assistant_response or {}).get("response", "")).strip()
    user_query = str((assistant_response or {}).get("user_query", "")).strip()
    user_content = str(user_content or "").strip()
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
            )
        )
        _prune_locked()


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
                f"Request: {_compact(exchange.user_query or exchange.user_content)}\n"
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

    sections = [
        "Answer the latest interviewer question as a software engineering interview candidate.",
    ]

    if exchanges:
        lines = []
        for idx, exchange in enumerate(exchanges, start=1):
            lines.append(
                f"Prior answer {idx} ({exchange.mode}, {exchange.timestamp})\n"
                f"Question: {_compact(exchange.user_query or exchange.user_content, 350)}\n"
                f"Answer: {_compact(exchange.response, 450)}"
            )
        sections.append("Recent answer context:\n" + "\n\n".join(lines))

    if transcripts:
        lines = []
        for turn in transcripts:
            speaker = "Interviewer" if turn.source == "desktop" else "Me"
            lines.append(f"{turn.timestamp} {speaker}: {_compact(turn.text, 700)}")
        sections.append("Recent live transcript turns:\n" + "\n".join(lines))

    if current_input:
        sections.append(f"Latest interviewer question:\n{current_input}")

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
