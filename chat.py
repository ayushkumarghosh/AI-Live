import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import OpenAI

from env_loader import load_env_file
from session_context import build_context, clear_session_context, record_exchange


load_env_file()


ANALYSIS_MODEL = os.getenv("AZURE_OPENAI_ANALYSIS_DEPLOYMENT", "gpt-5.5")
AUTO_ANSWER_MODEL = os.getenv("AZURE_OPENAI_AUTO_ANSWER_DEPLOYMENT", "gpt-5.4-nano")

_analysis_client: Optional[OpenAI] = None
_auto_answer_client: Optional[OpenAI] = None


code_problem_prompt = (
    "Read the transcriptions and screenshots to solve coding problems. If a coding "
    "problem is present, briefly explain the naive and optimized approaches, then "
    "provide complete working code. If an existing code snippet or function signature "
    "is visible, preserve it and complete or extend that code directly."
)

general_analysis_prompt = (
    "Respond as if you are the candidate in a software engineering interview. "
    "Prioritize the latest interviewer question in the transcript. Answer first, then "
    "briefly explain the reasoning. Be concise, professional, and practical."
)

repeat_analysis_prompt = (
    "Use the previous context plus the latest transcription or screenshot to improve "
    "the answer. For coding problems, focus on the improved optimized solution rather "
    "than repeating the naive approach."
)

auto_answer_prompt = (
    "You are helping a software engineering interview candidate. Given the latest "
    "interviewer transcript, write a concise answer the candidate could say out loud. "
    "Do not mention that you are an AI assistant."
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
    print(f"{timestamp()} Chat history reset")


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
) -> Dict[str, str]:
    instructions = [
        "Return only JSON matching this schema: "
        '{"user_query": string, "response": string}.',
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
    record_exchange(content_text, response_json, mode)
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
    return _send_analysis_message(text_input, content_text, content_parts, mode="text")


def analyze_code_problem(
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
        "User's screens. Apply the coding problem instructions to any visible problem:",
        include_transcripts=include_transcripts,
        mode="code",
    )
    return _send_analysis_message(text_input, content_text, content_parts, code_problem_prompt, mode="code")


def analyze_repeat_problem(
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
        "User's screens. Use them with the prior chat context for this follow-up:",
        include_transcripts=include_transcripts,
        mode="repeat",
    )
    return _send_analysis_message(text_input, content_text, content_parts, repeat_analysis_prompt, mode="repeat")


def analyze_general_problem_no_thinking(
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
        "User's screens. Use them to answer the latest non-coding question:",
        include_transcripts=include_transcripts,
        mode="general",
    )
    return _send_analysis_message(text_input, content_text, content_parts, general_analysis_prompt, mode="general")


def generate_auto_answer(transcript: str) -> str:
    transcript = transcript.strip()
    if not transcript:
        return ""

    context_text = build_context(transcript, "auto", include_transcripts=True)
    try:
        response = _responses_create_with_retries(
            get_auto_answer_client(),
            model=AUTO_ANSWER_MODEL,
            instructions=auto_answer_prompt,
            input=context_text,
            max_output_tokens=1200,
            reasoning={"effort": "none"},
            text={"verbosity": "low"},
        )
    except Exception as exc:
        print(
            f"{timestamp()} Azure OpenAI auto-answer failed for deployment "
            f"{AUTO_ANSWER_MODEL!r}: {exc}",
            flush=True,
        )
        return ""

    answer = _extract_output_text(response).strip()
    if answer:
        record_exchange(context_text, {"user_query": transcript, "response": answer}, "auto")
    return answer
