"""Opt-in integration test. Uses the signed-in Codex account; no editor automation."""
import os
import tempfile
import unittest
from pathlib import Path
from project_guide.files import ProjectFiles
from project_guide.runner import CodexRunner
from project_guide.session import parse_guidance


@unittest.skipUnless(os.getenv('AI_LIVE_CODEX_SMOKE') == '1', 'Opt-in real Codex integration')
class LiveGuideTests(unittest.TestCase):
    def test_real_readonly_analysis_leaves_project_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='ai-live-smoke-') as directory:
            root = Path(directory)
            (root / 'README.md').write_text("In hello.py implement hello(name) to return exactly 'Hello ' + name. No tests need to run.", encoding='utf-8')
            (root / 'hello.py').write_text('def hello(name):\n    pass\n', encoding='utf-8')
            (root / '.codex').mkdir()
            (root / '.codex' / 'config.toml').write_text(
                '[hooks]\nSessionStart = [{hooks = [{type="command", command="cmd /c echo unexpected > hook-fired.txt"}]}]\n',
                encoding='utf-8')
            files = ProjectFiles(root)
            def all_files():
                return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            before = all_files()
            runner = CodexRunner()
            output = runner.run(root, {'action': 'analyze', 'problem_file': 'README.md'}, print)
            parse_guidance(output)
            self.assertTrue(output['steps'], (output, runner.diagnostics))
            self.assertEqual(output['steps'][0]['path'], 'hello.py')
            self.assertEqual(before, all_files())
            # Simulate the user's manual edit, then verify review does not write.
            (root / 'hello.py').write_text('def hello(name):\n    return "Hello " + name\n', encoding='utf-8')
            before_review = all_files()
            review = CodexRunner().run(root, {'action': 'final', 'problem_file': 'README.md',
                                               'previous_guidance': output}, print)
            parse_guidance(review)
            self.assertEqual(review['verdict'], 'looks_complete', review)
            self.assertEqual(before_review, all_files())
