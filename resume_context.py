from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


MAX_RESUME_CONTEXT_CHARS = 12000
APP_CACHE_DIR_NAME = "AI-Live"
RESUME_CACHE_FILENAME = "resume_context.json"

_RESUME_RELEVANCE_PATTERNS = (
    "resume",
    "cv",
    "background",
    "experience",
    "experienced",
    "work experience",
    "worked on",
    "worked with",
    "project",
    "projects",
    "tell me about yourself",
    "about yourself",
    "your role",
    "your contribution",
    "your responsibilities",
    "achievement",
    "achievements",
    "accomplishment",
    "accomplishments",
    "strength",
    "strengths",
    "weakness",
    "weaknesses",
    "why should we hire",
    "why hire you",
    "skills",
    "skill set",
    "tech stack",
    "challenging",
    "challenge",
    "previous company",
    "current company",
    "internship",
    "education",
    "degree",
    "leadership",
    "ownership",
)


@dataclass
class ResumeContext:
    path: str
    filename: str
    markdown: str
    loaded_at: str


_lock = threading.RLock()
_resume_context: Optional[ResumeContext] = None


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _clean_resume_markdown(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _trim_resume_markdown(text: str, limit: int = MAX_RESUME_CONTEXT_CHARS) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 80].rstrip() + "\n\n[Resume context truncated to fit prompt budget.]"


def _cache_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_CACHE_DIR_NAME
    return Path.home() / ".ai-live"


def resume_cache_path() -> Path:
    return _cache_dir() / RESUME_CACHE_FILENAME


def _write_resume_cache(context: ResumeContext) -> None:
    cache_path = resume_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(context.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


def _delete_resume_cache() -> None:
    try:
        resume_cache_path().unlink(missing_ok=True)
    except TypeError:
        cache_path = resume_cache_path()
        if cache_path.exists():
            cache_path.unlink()


def is_resume_context_relevant(question_text: str) -> bool:
    text = " ".join(str(question_text or "").casefold().split())
    if not text:
        return False
    return any(pattern in text for pattern in _RESUME_RELEVANCE_PATTERNS)


def set_resume_context(path: str, markdown: str, persist: bool = True) -> ResumeContext:
    clean_markdown = _clean_resume_markdown(markdown)
    if not clean_markdown:
        raise ValueError("No readable text was extracted from the resume PDF.")

    resume_path = Path(path)
    context = ResumeContext(
        path=str(resume_path),
        filename=resume_path.name,
        markdown=clean_markdown,
        loaded_at=_timestamp(),
    )

    global _resume_context
    with _lock:
        _resume_context = context
        if persist:
            _write_resume_cache(context)
    return context


def clear_resume_context(remove_cache: bool = True) -> None:
    global _resume_context
    with _lock:
        _resume_context = None
        if remove_cache:
            _delete_resume_cache()


def get_resume_context() -> Optional[ResumeContext]:
    with _lock:
        if _resume_context is None:
            return None
        return ResumeContext(**_resume_context.__dict__)


def get_resume_context_section(max_chars: int = MAX_RESUME_CONTEXT_CHARS) -> str:
    context = get_resume_context()
    if context is None:
        return ""

    return "\n".join(
        [
            "Candidate resume context:",
            (
                "Use this only when the interviewer asks about the candidate's experience, "
                "projects, skills, background, strengths, achievements, or when a personalized "
                "example would improve the answer. Do not invent details beyond this resume."
            ),
            f"Source file: {context.filename}",
            "Resume markdown:",
            _trim_resume_markdown(context.markdown, max_chars),
        ]
    )


def _convert_with_markitdown(path: Path, converter_factory: Optional[Callable[[], object]] = None) -> str:
    if converter_factory is None:
        from markitdown import MarkItDown

        converter_factory = MarkItDown

    converter = converter_factory()
    result = converter.convert(str(path))
    return str(getattr(result, "text_content", "") or "")


def _extract_with_pdfplumber(path: Path) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"## Page {index}\n\n{text}")
    return "\n\n".join(pages)


def _extract_with_pdfminer(path: Path) -> str:
    from pdfminer.high_level import extract_text

    return str(extract_text(str(path)) or "")


def _convert_resume_pdf_to_markdown(path: Path, converter_factory: Optional[Callable[[], object]] = None) -> str:
    errors = []

    try:
        markdown = _convert_with_markitdown(path, converter_factory=converter_factory)
        if _clean_resume_markdown(markdown):
            return markdown
        errors.append("MarkItDown returned no readable text.")
    except Exception as exc:
        errors.append(f"MarkItDown failed: {type(exc).__name__}: {exc}")

    for label, extractor in (
        ("pdfplumber", _extract_with_pdfplumber),
        ("pdfminer", _extract_with_pdfminer),
    ):
        try:
            markdown = extractor(path)
            if _clean_resume_markdown(markdown):
                return markdown
            errors.append(f"{label} returned no readable text.")
        except Exception as exc:
            errors.append(f"{label} failed: {type(exc).__name__}: {exc}")

    raise RuntimeError("Could not extract readable text from the resume PDF. " + " | ".join(errors))


def load_cached_resume_context() -> Optional[ResumeContext]:
    cache_path = resume_cache_path()
    if not cache_path.is_file():
        return None

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        markdown = _clean_resume_markdown(data.get("markdown", ""))
        if not markdown:
            _delete_resume_cache()
            return None

        context = ResumeContext(
            path=str(data.get("path", "")),
            filename=str(data.get("filename", "resume.pdf") or "resume.pdf"),
            markdown=markdown,
            loaded_at=str(data.get("loaded_at", "") or _timestamp()),
        )
    except Exception:
        _delete_resume_cache()
        return None

    global _resume_context
    with _lock:
        _resume_context = context
    return get_resume_context()


def load_resume_pdf(
    pdf_path: str,
    converter_factory: Optional[Callable[[], object]] = None,
    persist: bool = True,
) -> ResumeContext:
    path = Path(pdf_path).expanduser()
    if path.suffix.lower() != ".pdf":
        raise ValueError("Please choose a PDF resume file.")
    if not path.is_file():
        raise FileNotFoundError(f"Resume PDF was not found: {path}")

    markdown = _convert_resume_pdf_to_markdown(path, converter_factory=converter_factory)
    return set_resume_context(str(path), markdown, persist=persist)


def snapshot() -> dict:
    context = get_resume_context()
    if context is None:
        return {"loaded": False, "filename": "", "chars": 0, "loaded_at": ""}

    return {
        "loaded": True,
        "filename": context.filename,
        "chars": len(context.markdown),
        "loaded_at": context.loaded_at,
    }
