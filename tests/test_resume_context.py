import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import resume_context
import session_context


class FakeConversionResult:
    text_content = "# Candidate\n\nBuilt distributed caching systems with Redis."


class FakeConverter:
    def __init__(self):
        self.converted_path = None

    def convert(self, path):
        self.converted_path = path
        return FakeConversionResult()


class FailingConverter:
    def convert(self, path):
        raise ImportError("simulated markitdown import failure")


MINIMAL_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj
4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
5 0 obj << /Length 74 >> stream
BT /F1 24 Tf 72 720 Td (AI Live Resume Smoke Test) Tj ET
endstream endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000241 00000 n 
0000000311 00000 n 
trailer << /Root 1 0 R /Size 6 >>
startxref
435
%%EOF
"""


class ResumeContextTests(unittest.TestCase):
    def setUp(self):
        resume_context.clear_resume_context(remove_cache=False)
        session_context.clear_session_context()

    def tearDown(self):
        resume_context.clear_resume_context(remove_cache=False)
        session_context.clear_session_context()

    def test_load_resume_pdf_uses_markitdown_converter_and_stores_markdown(self):
        converter = FakeConverter()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name

        try:
            context = resume_context.load_resume_pdf(
                pdf_path,
                converter_factory=lambda: converter,
                persist=False,
            )
        finally:
            os.unlink(pdf_path)

        self.assertEqual(converter.converted_path, pdf_path)
        self.assertEqual(context.filename, os.path.basename(pdf_path))
        self.assertIn("Built distributed caching systems with Redis.", context.markdown)
        self.assertEqual(resume_context.snapshot()["loaded"], True)

    def test_resume_context_persists_to_local_cache_and_can_be_removed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "resume_context.json"
            with patch.object(resume_context, "resume_cache_path", return_value=cache_path):
                resume_context.set_resume_context(
                    "resume.pdf",
                    "# Candidate\n\nBuilt ranking services.",
                    persist=True,
                )
                self.assertTrue(cache_path.is_file())

                resume_context.clear_resume_context(remove_cache=False)
                self.assertEqual(resume_context.snapshot()["loaded"], False)

                cached = resume_context.load_cached_resume_context()
                self.assertIsNotNone(cached)
                self.assertEqual(cached.filename, "resume.pdf")
                self.assertIn("Built ranking services.", cached.markdown)

                resume_context.clear_resume_context(remove_cache=True)
                self.assertFalse(cache_path.exists())

    def test_load_resume_pdf_falls_back_to_pdf_extraction_when_markitdown_fails(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(MINIMAL_PDF)
            pdf_path = tmp.name

        try:
            context = resume_context.load_resume_pdf(
                pdf_path,
                converter_factory=lambda: FailingConverter(),
                persist=False,
            )
        finally:
            os.unlink(pdf_path)

        self.assertIn("AI Live Resume Smoke Test", context.markdown)

    def test_general_context_includes_resume_when_loaded(self):
        resume_context.set_resume_context(
            "resume.pdf",
            "# Candidate\n\nLed payments migration and owned Redis cache design.",
            persist=False,
        )

        context = session_context.build_context("Tell me about your projects.", "general")

        self.assertIn("Candidate resume context:", context)
        self.assertIn("Led payments migration", context)
        self.assertIn("Do not invent details beyond this resume.", context)

    def test_code_context_does_not_include_resume(self):
        resume_context.set_resume_context("resume.pdf", "Personal project details", persist=False)

        context = session_context.build_context("Solve two sum.", "code")

        self.assertNotIn("Candidate resume context:", context)
        self.assertNotIn("Personal project details", context)

    def test_auto_answer_context_includes_resume_when_loaded(self):
        resume_context.set_resume_context(
            "resume.pdf",
            "# Candidate\n\nBuilt observability dashboards for payment services.",
            persist=False,
        )
        session_context.record_transcript("Tell me about a project from your resume.", "desktop")

        context = session_context.build_auto_answer_context(
            "Tell me about a project from your resume.",
            transcript_turns=1,
            exchange_count=0,
        )

        self.assertIn("Candidate resume context:", context)
        self.assertIn("Built observability dashboards", context)
        self.assertIn("Interviewer turns to answer together in the single visible response", context)

    def test_auto_answer_context_excludes_resume_for_non_personal_question(self):
        resume_context.set_resume_context(
            "resume.pdf",
            "# Candidate\n\nBuilt observability dashboards for payment services.",
            persist=False,
        )
        session_context.record_transcript("How does a hash map handle collisions?", "desktop")

        context = session_context.build_auto_answer_context(
            "How does a hash map handle collisions?",
            transcript_turns=1,
            exchange_count=0,
        )

        self.assertNotIn("Candidate resume context:", context)
        self.assertNotIn("Built observability dashboards", context)


if __name__ == "__main__":
    unittest.main()
