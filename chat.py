import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import OpenAI

from env_loader import load_env_file
from session_context import (
    build_context,
    clear_session_context,
    find_repeated_exchange,
    record_exchange,
)


load_env_file()


ANALYSIS_MODEL = os.getenv("AZURE_OPENAI_ANALYSIS_DEPLOYMENT", "gpt-5.5")

_analysis_client: Optional[OpenAI] = None


candidate_answer_style_prompt = (
    "Write the response like an Indian software engineer in an interview would say it "
    "out loud: practical, direct, and conversational Indian English, close to how we "
    "chat here. Use first person where it fits, prefer simple spoken sentences, and "
    "include concrete reasoning without over-explaining. It is okay to sound a little "
    "informal and human, but do not force slang, Hinglish, filler words, or accent-like "
    "wording. Avoid sounding overly polished, scripted, corporate, or like an AI "
    "assistant. Keep the technical content accurate and interview-appropriate."
)

code_problem_prompt = (
    "Read the supplied text and screenshots to solve coding problems. If a coding "
    "problem is present, briefly explain the naive and optimized approaches, then "
    "provide complete working code. If an existing code snippet or function signature "
    "is visible, preserve it and complete or extend that code directly."
)

general_analysis_prompt = (
    "Respond as if you are the candidate in a software engineering interview. "
    "Prioritize the current user request and any relevant screenshot. Answer first, then "
    "briefly explain the reasoning. If candidate resume context is provided, use it "
    "only when the question asks about experience, background, projects, skills, "
    "achievements, strengths, or when a personalized example is clearly useful. Do "
    "not invent resume details. Be concise, professional, and practical."
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
        text_parts.append(f"Current text selected or submitted by the user:\n{text_input}")
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
