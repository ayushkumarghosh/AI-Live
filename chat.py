import base64
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests
from google import genai
from google.genai import types

from env_loader import load_env_file


load_env_file()


GEMINI_FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-pro")
GEMINI_GENERAL_MODEL = os.getenv("GEMINI_GENERAL_MODEL", "gemini-2.0-flash")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "tngtech/deepseek-r1t-chimera:free")

_client: Optional[genai.Client] = None
_chat_flash = None
chat_history = []
deepseek_chat_history = []


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


def timestamp():
    return f"[{datetime.now().strftime('%H:%M:%S')}]"


def _gemini_api_key() -> str:
    api_key = os.getenv("GEMINI_API", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API is not set. Add it to .env or your environment before running analysis.")
    return api_key


def _openrouter_api_key() -> str:
    api_key = (os.getenv("DEEPSEEK") or os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK is not set. Add your OpenRouter key to .env before using DeepSeek.")
    return api_key


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=_gemini_api_key())
    return _client


def get_chat_flash():
    global _chat_flash
    if _chat_flash is None:
        _chat_flash = get_client().chats.create(model=GEMINI_FLASH_MODEL)
    return _chat_flash


def reset_chat_history():
    global _chat_flash, chat_history, deepseek_chat_history
    _chat_flash = None
    chat_history = []
    deepseek_chat_history = []
    print(f"{timestamp()} Chat history reset")


def clear_chat_history():
    reset_chat_history()
    return True


def prepare_image_parts(images_base64: List[str], image_format: str) -> List[types.Part]:
    image_parts = []
    mime_format = "jpeg" if image_format.lower() in {"jpg", "jpeg"} else image_format.lower()

    for image_base64 in images_base64:
        try:
            image_parts.append(
                types.Part.from_bytes(
                    data=base64.b64decode(image_base64),
                    mime_type=f"image/{mime_format}",
                )
            )
        except Exception as exc:
            print(f"{timestamp()} Warning: failed to process image: {exc}", flush=True)

    return image_parts


def prepare_audio_parts(audio_base64: str, audio_format: str, audio_type: str = "audio") -> List[types.Part]:
    if not audio_base64 or len(audio_base64) <= 100:
        return []

    try:
        return [
            types.Part.from_bytes(
                data=base64.b64decode(audio_base64),
                mime_type=f"audio/{audio_format}",
            )
        ]
    except Exception as exc:
        print(f"{timestamp()} Warning: failed to process {audio_type}: {exc}", flush=True)
        return []


def _response_schema():
    return {
        "type": "object",
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


def _record_history(user_content, response_json):
    chat_history.append({"user_content": user_content, "assistant_response": response_json})
    if len(chat_history) > 50:
        del chat_history[:-50]


def _manual_content(text_input: str, images_base64: List[str], image_format: str, screen_label: str) -> list:
    content_parts = []
    if text_input:
        content_parts.append(f"Current query/transcription:\n{text_input}")
    else:
        content_parts.append("No transcript was provided. Use the screenshot context if available.")

    if images_base64:
        content_parts.append(screen_label)
        content_parts.extend(prepare_image_parts(images_base64, image_format))

    return content_parts


def _send_chat_message(text_input: str, content_parts: list, system_instruction: Optional[str] = None) -> Dict[str, str]:
    config_kwargs = {
        "temperature": 0.6,
        "max_output_tokens": 60000,
        "response_mime_type": "application/json",
        "response_schema": _response_schema(),
    }
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction

    response = get_chat_flash().send_message(
        message=content_parts,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    response_json = _parse_json_response(response.text or "", text_input)
    _record_history(content_parts, response_json)
    return response_json


def analyze_with_text_input(
    text_input: str,
    images_base64: List[str],
    image_format: str,
    desktop_audio_base64: str = "",
):
    content_parts = _manual_content(
        text_input,
        images_base64,
        image_format,
        "User's screens. Use them only when relevant to the current query:",
    )
    return _send_chat_message(text_input, content_parts)


def analyze_code_problem(
    text_input: str,
    images_base64: List[str],
    image_format: str,
    desktop_audio_base64: str = "",
):
    content_parts = _manual_content(
        text_input,
        images_base64,
        image_format,
        "User's screens. Apply the coding problem instructions to any visible problem:",
    )
    return _send_chat_message(text_input, content_parts, code_problem_prompt)


def analyze_repeat_problem(
    text_input: str,
    images_base64: List[str],
    image_format: str,
    desktop_audio_base64: str = "",
):
    content_parts = _manual_content(
        text_input,
        images_base64,
        image_format,
        "User's screens. Use them with the prior chat context for this follow-up:",
    )
    return _send_chat_message(text_input, content_parts, repeat_analysis_prompt)


def analyze_general_problem_no_thinking(
    text_input: str,
    images_base64: List[str],
    image_format: str,
    desktop_audio_base64: str = "",
):
    content_parts = _manual_content(
        text_input,
        images_base64,
        image_format,
        "User's screens. Use them to answer the latest non-coding question:",
    )
    response = get_client().models.generate_content(
        model=GEMINI_GENERAL_MODEL,
        contents=content_parts,
        config=types.GenerateContentConfig(
            system_instruction=general_analysis_prompt,
            temperature=0.6,
            max_output_tokens=8000,
            response_mime_type="application/json",
            response_schema=_response_schema(),
        ),
    )
    response_json = _parse_json_response(response.text or "", text_input)
    _record_history(content_parts, response_json)
    return response_json


def transcribe_images_to_text(images_base64: List[str], image_format: str) -> str:
    if not images_base64:
        return ""

    content_parts = [
        "Describe these screenshots in detail. Focus on text, code, UI state, and error messages."
    ]
    content_parts.extend(prepare_image_parts(images_base64, image_format))

    for retry in range(3):
        try:
            response = get_client().models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=8000),
            )
            return response.text or ""
        except Exception as exc:
            if retry == 2:
                print(f"{timestamp()} Failed to transcribe images: {exc}", flush=True)
                return "Failed to transcribe image content."
            time.sleep(1)

    return ""


def transcribe_audio_to_text(audio_base64: str, audio_format: str, audio_type: str = "desktop") -> str:
    audio_parts = prepare_audio_parts(audio_base64, audio_format, audio_type)
    if not audio_parts:
        return ""

    content_parts = [f"Transcribe this {audio_type} audio accurately."]
    content_parts.extend(audio_parts)

    for retry in range(3):
        try:
            response = get_client().models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=4000),
            )
            return response.text or ""
        except Exception as exc:
            if retry == 2:
                print(f"{timestamp()} Failed to transcribe {audio_type} audio: {exc}", flush=True)
                return f"Failed to transcribe {audio_type} audio content."
            time.sleep(1)

    return ""


def call_deepseek_api(messages: List[Dict], max_tokens: int = 50000) -> str:
    headers = {
        "Authorization": f"Bearer {_openrouter_api_key()}",
        "Content-Type": "application/json",
    }
    data = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }

    for retry in range(3):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as exc:
            if retry == 2:
                raise RuntimeError(f"DeepSeek API call failed after 3 attempts: {exc}") from exc
            print(f"{timestamp()} DeepSeek API call failed, retrying: {exc}", flush=True)
            time.sleep(5)

    return ""


def analyze_with_deepseek_model(
    text_input: str,
    images_base64: List[str],
    image_format: str,
    desktop_audio_base64: str = "",
):
    global deepseek_chat_history

    image_transcription = transcribe_images_to_text(images_base64, image_format) if images_base64 else ""
    context_parts = []
    if text_input.strip():
        context_parts.append(f"User's text query: {text_input}")
    if image_transcription:
        context_parts.append(f"Screen content description: {image_transcription}")
    if not context_parts:
        context_parts.append("Please provide a helpful response.")

    messages = []
    for exchange in deepseek_chat_history[-10:]:
        messages.append({"role": "user", "content": exchange["user_message"]})
        messages.append({"role": "assistant", "content": exchange["assistant_response"]})

    context_message = "\n\n".join(context_parts)
    messages.append({"role": "user", "content": context_message})

    response_text = call_deepseek_api(messages, max_tokens=160000)
    deepseek_chat_history.append({"user_message": context_message, "assistant_response": response_text})
    deepseek_chat_history = deepseek_chat_history[-20:]

    return {"user_query": text_input, "response": response_text}
