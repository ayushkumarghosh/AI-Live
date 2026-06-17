import json
import os
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI

from env_loader import load_env_file
from session_context import (
    build_context,
    commit_auto_answer_turn,
    clear_session_context,
    find_repeated_exchange,
    prepare_auto_answer_turn,
    record_exchange,
)


load_env_file()


ANALYSIS_MODEL = os.getenv("AZURE_OPENAI_ANALYSIS_DEPLOYMENT", "gpt-5.5")
AUTO_ANSWER_MODEL = os.getenv("AZURE_OPENAI_AUTO_ANSWER_DEPLOYMENT", "gpt-5.4-nano")
AUTO_ANSWER_STREAMING = os.getenv("AUTO_ANSWER_STREAMING", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTO_ANSWER_LATENCY_LOG = os.getenv("AUTO_ANSWER_LATENCY_LOG", "false").strip().lower() in {"1", "true", "yes", "on"}

_analysis_client: Optional[OpenAI] = None
_auto_answer_client: Optional[OpenAI] = None


candidate_answer_style_prompt = (
    "Write the response like an Indian software engineering interview candidate would "
    "say it out loud: natural, direct, and conversational Indian English. Use first "
    "person where it fits, prefer simple spoken sentences, and avoid sounding overly "
    "polished, scripted, or like an AI assistant. Keep the technical content accurate "
    "and interview-appropriate."
)

code_problem_prompt = (
    "Read the transcriptions and screenshots to solve coding problems. If a coding "
    "problem is present, briefly explain the naive and optimized approaches, then "
    "provide complete working code. If an existing code snippet or function signature "
    "is visible, preserve it and complete or extend that code directly."
)

general_analysis_prompt = (
    "Respond as if you are the candidate in a software engineering interview. "
    "Prioritize the latest interviewer question in the transcript. Answer first, then "
    "briefly explain the reasoning. If candidate resume context is provided, use it "
    "only when the question asks about experience, background, projects, skills, "
    "achievements, strengths, or when a personalized example is clearly useful. Do "
    "not invent resume details. Be concise, professional, and practical."
)

auto_answer_prompt = (
    "You are helping a software engineering interview candidate. Given the target "
    "interviewer turns and recent conversation, write one concise answer the candidate "
    "could say out loud. Only the latest generated answer is visible to the candidate, "
    "so the response must be self-contained and cover the target interviewer turns "
    "together. "
    "Recent transcript context may include both speakers: desktop audio is the "
    "Interviewer, and microphone audio is the Interviewee/Candidate. Treat microphone "
    "transcriptions as what the candidate already said or clarifying questions they "
    "asked, not as questions to answer. If the interviewer question was split "
    "across pauses, combine the latest related interviewer turns. If the candidate "
    "asked a clarifying question and the interviewer answered it, use that clarified "
    "context to answer the latest interviewer question or follow-up. When the context "
    "contains an 'Interviewer turns to answer together in the single visible response' "
    "section, use that section as the answer target. Treat interviewer statements, "
    "confirmations, and constraints in that target section as context to fold into the "
    "same answer. Do not answer the latest desktop transcript merely because it is last. "
    "If candidate resume context is provided, use it only when the question asks about "
    "experience, background, projects, skills, achievements, strengths, or when a "
    "personalized example is clearly useful. Do not invent resume details. "
    "Return only the single answer, and do not mention that you are an AI assistant.\n\n"
    + candidate_answer_style_prompt
)

auto_answer_revision_prompt = (
    "You are updating the single interview auto-answer that is already visible for "
    "the current conversation segment. Return the complete updated visible answer "
    "only. The app will replace the visible answer with exactly your output, with no "
    "local patching or post-processing. Keep the previous answer's wording unchanged "
    "where it is still correct, and only add, remove, or minimally edit text needed "
    "to account for the latest interviewer turn and the current segment context. "
    "Do not duplicate the previous answer as a separate paragraph. If the latest "
    "turn does not require a change, return the previous visible answer exactly. "
    "Do not explain your edits, do not include JSON, and do not mention that you are "
    "an AI assistant.\n\n"
    + candidate_answer_style_prompt
)

repeat_correction_prompt = (
    "The current request appears to repeat a previous analysis request. Audit the "
    "previous answer for mistakes, omissions, and incorrect assumptions, then provide "
    "the corrected answer. Do not simply restate the previous answer."
)

code_repeat_correction_prompt = (
    repeat_correction_prompt
    + " For repeated coding questions, if screenshots are provided, inspect them for "
    "visible compiler, runtime, test, editor, or UI errors and use those errors to "
    "correct the solution. If no screenshot is provided, do not claim that the screen "
    "was checked."
)


def timestamp():
    return f"[{datetime.now().strftime('%H:%M:%S')}]"


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
        if parsed <= 0:
            raise ValueError("must be positive")
        return parsed
    except ValueError:
        print(f"{timestamp()} Invalid {name}={value!r}; using {default}", flush=True)
        return default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
        if parsed < 0:
            raise ValueError("must be non-negative")
        return parsed
    except ValueError:
        print(f"{timestamp()} Invalid {name}={value!r}; using {default}", flush=True)
        return default


AUTO_ANSWER_MAX_OUTPUT_TOKENS = _int_env("AUTO_ANSWER_MAX_OUTPUT_TOKENS", 500)
AUTO_ANSWER_CONTEXT_TURNS = _int_env("AUTO_ANSWER_CONTEXT_TURNS", 6)
AUTO_ANSWER_CONTEXT_EXCHANGES = _int_env("AUTO_ANSWER_CONTEXT_EXCHANGES", 2)
AUTO_ANSWER_TARGET_INTERVIEWER_TURNS = _int_env("AUTO_ANSWER_TARGET_INTERVIEWER_TURNS", 5)
AUTO_ANSWER_SEGMENT_GAP_SECONDS = _float_env("AUTO_ANSWER_SEGMENT_GAP_SECONDS", 45.0)
AUTO_ANSWER_TOPIC_OVERLAP_MIN = _float_env("AUTO_ANSWER_TOPIC_OVERLAP_MIN", 0.18)


def _latency_log(event: str, start_at: Optional[float] = None, **fields):
    if not AUTO_ANSWER_LATENCY_LOG:
        return

    elapsed = ""
    if start_at is not None:
        elapsed = f" +{(time.perf_counter() - start_at) * 1000:.0f}ms"
    details = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    if details:
        details = f" {details}"
    print(f"{timestamp()} latency auto_answer.{event}{elapsed}{details}", flush=True)


def _required_env(name: str, fallback_name: Optional[str] = None) -> str:
    value = os.getenv(name, "").strip()
    if not value and fallback_name:
        value = os.getenv(fallback_name, "").strip()
    if not value:
        if fallback_name:
            raise RuntimeError(
                f"{name} is not set, and fallback {fallback_name} is not set. "
                "Add one of them to .env or your environment."
            )
        raise RuntimeError(f"{name} is not set. Add it to .env or your environment.")
    return value


def _azure_base_url(endpoint_name: str) -> str:
    endpoint = _required_env(endpoint_name, "AZURE_OPENAI_ENDPOINT").rstrip("/")
    if endpoint.endswith("/openai/v1"):
        return endpoint + "/"
    if endpoint.endswith("/openai"):
        return endpoint + "/v1/"
    return endpoint + "/openai/v1/"


def get_analysis_client() -> OpenAI:
    global _analysis_client
    if _analysis_client is None:
        _analysis_client = OpenAI(
            api_key=_required_env("AZURE_OPENAI_ANALYSIS_API_KEY", "AZURE_OPENAI_API_KEY"),
            base_url=_azure_base_url("AZURE_OPENAI_ANALYSIS_ENDPOINT"),
        )
    return _analysis_client


def get_auto_answer_client() -> OpenAI:
    global _auto_answer_client
    if _auto_answer_client is None:
        _auto_answer_client = OpenAI(
            api_key=_required_env("AZURE_OPENAI_AUTO_ANSWER_API_KEY", "AZURE_OPENAI_API_KEY"),
            base_url=_azure_base_url("AZURE_OPENAI_AUTO_ANSWER_ENDPOINT"),
        )
    return _auto_answer_client


def reset_chat_history():
    clear_session_context()
    print(f"{timestamp()} Answer context reset")


def clear_chat_history():
    reset_chat_history()
    return True


def _response_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "user_query": {"type": "string"},
            "response": {"type": "string"},
        },
        "required": ["user_query", "response"],
    }


def _parse_json_response(response_text: str, fallback_query: str) -> Dict[str, str]:
    try:
        parsed = json.loads(response_text)
        if isinstance(parsed, dict):
            return {
                "user_query": str(parsed.get("user_query", fallback_query)),
                "response": str(parsed.get("response", "")),
            }
    except json.JSONDecodeError:
        print(f"{timestamp()} Warning: model response was not valid JSON", flush=True)

    return {"user_query": fallback_query, "response": response_text}


def _image_content(images_base64: List[str], image_format: str) -> List[Dict[str, str]]:
    mime_format = "jpeg" if image_format.lower() in {"jpg", "jpeg"} else image_format.lower()
    image_parts = []

    for image_base64 in images_base64:
        if not image_base64:
            continue
        image_parts.append(
            {
                "type": "input_image",
                "image_url": f"data:image/{mime_format};base64,{image_base64}",
            }
        )

    return image_parts


def _manual_content(
    text_input: str,
    images_base64: List[str],
    image_format: str,
    screen_label: str,
    include_history: bool = True,
    include_transcripts: bool = True,
    mode: str = "analysis",
) -> tuple[str, List[Dict[str, str]]]:
    text_parts = []
    if include_history:
        text_parts.append(build_context(text_input, mode, include_transcripts=include_transcripts))

    if text_input:
        text_parts.append(f"Current query/transcription selected by the user:\n{text_input}")
    else:
        text_parts.append("No transcript was provided. Use the screenshot context if available.")

    if images_base64:
        text_parts.append(screen_label)

    text_content = "\n\n".join(text_parts)
    content: List[Dict[str, str]] = [{"type": "input_text", "text": text_content}]
    content.extend(_image_content(images_base64, image_format))
    return text_content, content


def _append_manual_text(
    content_text: str,
    content_parts: List[Dict[str, str]],
    extra_text: str,
) -> tuple[str, List[Dict[str, str]]]:
    if not extra_text:
        return content_text, content_parts

    content_text = f"{content_text}\n\n{extra_text}"
    if content_parts and content_parts[0].get("type") == "input_text":
        content_parts[0] = {**content_parts[0], "text": content_text}
    return content_text, content_parts


def _repeat_correction_context(mode: str, repeat_match: Dict[str, str], has_screenshots: bool) -> str:
    previous_question = repeat_match.get("current_input") or repeat_match.get("user_query") or ""
    previous_answer = repeat_match.get("response") or ""
    mode_label = "Code" if mode == "code" else "General"

    lines = [
        "Automatic repeat correction:",
        f"The current {mode_label} Analysis request appears to be the same as this prior {mode} request.",
        "Review the prior answer for mistakes, omissions, and incorrect assumptions before answering.",
        f"Prior question:\n{previous_question}",
        f"Prior answer:\n{previous_answer}",
    ]

    if mode == "code":
        if has_screenshots:
            lines.append(
                "Screenshot context is attached. Inspect it for visible compiler, runtime, "
                "test, editor, or UI errors and incorporate any fixes into the answer."
            )
        else:
            lines.append(
                "No screenshot was provided for this repeated code request, so do not claim "
                "to have checked the screen for errors."
            )

    return "\n\n".join(lines)


def _analysis_instruction(base_prompt: str, repeat_match: Optional[Dict[str, str]], mode: str) -> str:
    if not repeat_match:
        return base_prompt
    correction_prompt = code_repeat_correction_prompt if mode == "code" else repeat_correction_prompt
    return f"{base_prompt}\n\n{correction_prompt}"


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    chunks = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(text)
    return "".join(chunks)


def _responses_create_with_retries(client: OpenAI, **kwargs):
    last_exc = None
    for retry in range(3):
        try:
            return client.responses.create(**kwargs)
        except Exception as exc:
            last_exc = exc
            if retry == 2:
                break
            print(f"{timestamp()} Azure OpenAI request failed, retrying: {exc}", flush=True)
            time.sleep(1.5)
    raise last_exc


def _extract_stream_delta(event: Any) -> str:
    event_type = getattr(event, "type", None)
    if not event_type and isinstance(event, dict):
        event_type = event.get("type")
    if event_type != "response.output_text.delta":
        return ""

    if isinstance(event, dict):
        return str(event.get("delta") or "")
    return str(getattr(event, "delta", "") or "")


def _send_analysis_message(
    text_input: str,
    content_text: str,
    content_parts: List[Dict[str, str]],
    system_instruction: Optional[str] = None,
    mode: str = "analysis",
    current_input: Optional[str] = None,
) -> Dict[str, str]:
    instructions = [
        "Return only JSON matching this schema: "
        '{"user_query": string, "response": string}.',
        candidate_answer_style_prompt,
    ]
    if system_instruction:
        instructions.append(system_instruction)

    try:
        response = _responses_create_with_retries(
            get_analysis_client(),
            model=ANALYSIS_MODEL,
            instructions="\n\n".join(instructions),
            input=[{"role": "user", "content": content_parts}],
            max_output_tokens=12000,
            reasoning={"effort": "none"},
            text={
                "format": {
                    "type": "json_schema",
                    "name": "analysis_response",
                    "schema": _response_schema(),
                    "strict": True,
                },
                "verbosity": "medium",
            },
        )
    except Exception as exc:
        raise RuntimeError(
            f"Azure OpenAI analysis request failed for deployment {ANALYSIS_MODEL!r} "
            "with reasoning effort disabled (reasoning.effort='none'). "
            f"Original error: {exc}"
        ) from exc

    response_json = _parse_json_response(_extract_output_text(response), text_input)
    record_exchange(content_text, response_json, mode, current_input=current_input or text_input)
    return response_json


def analyze_with_text_input(
    text_input: str,
    images_base64: List[str],
    image_format: str,
    desktop_audio_base64: str = "",
    include_transcripts: bool = True,
):
    content_text, content_parts = _manual_content(
        text_input,
        images_base64,
        image_format,
        "User's screens. Use them only when relevant to the current query:",
        include_transcripts=include_transcripts,
        mode="text",
    )
    return _send_analysis_message(text_input, content_text, content_parts, mode="text", current_input=text_input)


def analyze_code_problem(
    text_input: str,
    images_base64: List[str],
    image_format: str,
    desktop_audio_base64: str = "",
    include_transcripts: bool = True,
):
    repeat_match = find_repeated_exchange(text_input, "code")
    content_text, content_parts = _manual_content(
        text_input,
        images_base64,
        image_format,
        "User's screens. Apply the coding problem instructions to any visible problem:",
        include_transcripts=include_transcripts,
        mode="code",
    )
    if repeat_match:
        content_text, content_parts = _append_manual_text(
            content_text,
            content_parts,
            _repeat_correction_context("code", repeat_match, bool(images_base64)),
        )
    return _send_analysis_message(
        text_input,
        content_text,
        content_parts,
        _analysis_instruction(code_problem_prompt, repeat_match, "code"),
        mode="code",
        current_input=text_input,
    )


def analyze_general_problem_no_thinking(
    text_input: str,
    images_base64: List[str],
    image_format: str,
    desktop_audio_base64: str = "",
    include_transcripts: bool = True,
):
    repeat_match = find_repeated_exchange(text_input, "general")
    content_text, content_parts = _manual_content(
        text_input,
        images_base64,
        image_format,
        "User's screens. Use them to answer the latest non-coding question:",
        include_transcripts=include_transcripts,
        mode="general",
    )
    if repeat_match:
        content_text, content_parts = _append_manual_text(
            content_text,
            content_parts,
            _repeat_correction_context("general", repeat_match, bool(images_base64)),
        )
    return _send_analysis_message(
        text_input,
        content_text,
        content_parts,
        _analysis_instruction(general_analysis_prompt, repeat_match, "general"),
        mode="general",
        current_input=text_input,
    )


def _generate_auto_answer_streaming(
    context_text: str,
    on_delta: Optional[Callable[[str, str], None]] = None,
    instructions: str = auto_answer_prompt,
) -> str:
    request_started_at = time.perf_counter()
    _latency_log("request_started")

    answer_parts = []
    first_delta_at = None
    with get_auto_answer_client().responses.stream(
        model=AUTO_ANSWER_MODEL,
        instructions=instructions,
        input=context_text,
        max_output_tokens=AUTO_ANSWER_MAX_OUTPUT_TOKENS,
        reasoning={"effort": "none"},
        text={"verbosity": "low"},
    ) as stream:
        for event in stream:
            delta = _extract_stream_delta(event)
            if not delta:
                continue
            if first_delta_at is None:
                first_delta_at = time.perf_counter()
                _latency_log("first_token", request_started_at)
            answer_parts.append(delta)
            if on_delta:
                on_delta(delta, "".join(answer_parts))

    answer = "".join(answer_parts).strip()
    _latency_log("answer_complete", first_delta_at or request_started_at, chars=len(answer))
    return answer


def _responses_create_auto_answer(context_text: str, instructions: str) -> str:
    response = _responses_create_with_retries(
        get_auto_answer_client(),
        model=AUTO_ANSWER_MODEL,
        instructions=instructions,
        input=context_text,
        max_output_tokens=AUTO_ANSWER_MAX_OUTPUT_TOKENS,
        reasoning={"effort": "none"},
        text={"verbosity": "low"},
    )
    return _extract_output_text(response)


def _revision_context(context_text: str, previous_answer: str, latest_transcript: str) -> str:
    return "\n\n".join(
        [
            context_text,
            "Exact previous visible answer for this active conversation segment:",
            str(previous_answer or ""),
            "Return the complete updated visible answer. The UI will display exactly what you return.",
            f"Latest interviewer transcript to incorporate:\n{latest_transcript}",
        ]
    )


def _is_generation_current(is_current: Optional[Callable[[], bool]]) -> bool:
    if not is_current:
        return True
    try:
        return bool(is_current())
    except Exception as exc:
        print(f"{timestamp()} Auto-answer current-turn check failed: {exc}", flush=True)
        return False


def _commit_auto_answer_if_current(
    turn_context: Dict[str, object],
    answer: str,
    is_current: Optional[Callable[[], bool]],
) -> bool:
    if not str(answer or "").strip() or not _is_generation_current(is_current):
        return False

    commit_auto_answer_turn(turn_context, answer)
    context_text = str(turn_context.get("context_text") or "")
    target_summary = str(turn_context.get("target_summary") or "")
    record_exchange(
        context_text,
        {"user_query": target_summary, "response": answer},
        "auto",
        current_input=target_summary,
    )
    return True


def _call_reset_if_needed(
    turn_context: Dict[str, object],
    on_reset: Optional[Callable[[], None]],
    is_current: Optional[Callable[[], bool]],
) -> None:
    if not on_reset or not turn_context.get("should_clear_previous_answer"):
        return
    if not _is_generation_current(is_current):
        return
    on_reset()


def generate_auto_answer(
    transcript: str,
    on_delta: Optional[Callable[[str, str], None]] = None,
    previous_answer: Optional[str] = None,
    on_reset: Optional[Callable[[], None]] = None,
    is_current: Optional[Callable[[], bool]] = None,
) -> str:
    transcript = transcript.strip()
    if not transcript:
        return ""

    turn_context = prepare_auto_answer_turn(
        transcript,
        transcript_turns=AUTO_ANSWER_CONTEXT_TURNS,
        exchange_count=AUTO_ANSWER_CONTEXT_EXCHANGES,
        target_interviewer_turns=AUTO_ANSWER_TARGET_INTERVIEWER_TURNS,
        segment_gap_seconds=AUTO_ANSWER_SEGMENT_GAP_SECONDS,
        topic_overlap_min=AUTO_ANSWER_TOPIC_OVERLAP_MIN,
        previous_answer=previous_answer,
    )
    context_text = str(turn_context.get("context_text") or "")
    prior_answer = str(turn_context.get("previous_answer") or "")
    is_revision = bool(prior_answer and not turn_context.get("starts_new_segment"))
    instructions = auto_answer_prompt

    _call_reset_if_needed(turn_context, on_reset, is_current)

    should_stream = bool(AUTO_ANSWER_STREAMING and not is_revision)

    if should_stream:
        try:
            answer = _generate_auto_answer_streaming(
                context_text,
                on_delta=on_delta,
                instructions=instructions,
            )
            _commit_auto_answer_if_current(turn_context, answer, is_current)
            return answer
        except Exception as exc:
            print(
                f"{timestamp()} Azure OpenAI streaming auto-answer failed for deployment "
                f"{AUTO_ANSWER_MODEL!r}; falling back to non-streaming request: {exc}",
                flush=True,
            )

    request_started_at = time.perf_counter()
    _latency_log("request_started")
    try:
        request_text = _revision_context(context_text, prior_answer, transcript) if is_revision else context_text
        raw_answer = _responses_create_auto_answer(
            request_text,
            auto_answer_revision_prompt if is_revision else instructions,
        )
    except Exception as exc:
        print(
            f"{timestamp()} Azure OpenAI auto-answer failed for deployment "
            f"{AUTO_ANSWER_MODEL!r}: {exc}",
            flush=True,
        )
        return ""

    answer = raw_answer
    _latency_log("answer_complete", request_started_at, chars=len(answer))
    if answer and on_delta and not is_revision:
        on_delta(answer, answer)
    _commit_auto_answer_if_current(turn_context, answer, is_current)
    return answer
