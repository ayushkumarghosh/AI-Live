"""Opt-in integration test. Uses the signed-in Codex account; no editor automation."""
import os
import tempfile
import unittest
from pathlib import Path
from project_guide.files import ProjectFiles
from project_guide.runner import CodexRunner
from project_guide.session import parse_guidance, PromptSession


@unittest.skipUnless(os.getenv('AI_LIVE_CODEX_SMOKE') == '1', 'Opt-in real Codex integration')
class LiveGuideTests(unittest.TestCase):
    def test_truncated_terminal_review_distinguishes_complete_and_missing_evidence(self):
        with tempfile.TemporaryDirectory(prefix='ai-live-tail-smoke-') as directory:
            root = Path(directory)
            (root / 'README.md').write_text('Implement hello(name) in hello.py returning "Hello " + name. Acceptance: normal and empty names. Confirm design before edits.', encoding='utf-8')
            (root / 'hello.py').write_text('def hello(name):\n    pass\n', encoding='utf-8')
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            context = {'mode': 'prompt', 'action': 'check_output', 'problem_file': 'README.md',
                'current_prompt': 'Read-only analysis: read only README.md and return STATE_1 with stated requirements, acceptance criteria, constraints and open questions. Do not edit or run commands.',
                'accepted_requirements': '', 'conversation': {'updates': []},
                'terminal_output': {'command': 'codex', 'running': True, 'truncated': True, 'exit_code': None,
                    'output': 'STATE_1\nConfirmed: README.md requires hello(name) in hello.py returning exactly "Hello " + name. Acceptance: normal and empty names. Constraint: confirm design before edits. No open questions. No source investigated, edits made, or commands run. End of response.'}}
            result = CodexRunner().run(root, context, print)
            # The guide may inspect the tiny implementation itself and request
            # design approval, or issue another read-only investigation prompt.
            self.assertIn(result['status'], ('ready', 'clarification'), result)
            session = PromptSession(root, 'README.md', 'smoke')
            session.accept(session.begin(), result)
            self.assertRegex(result['findings'].lower(), r'truncat|limited|partial|older|incomplete|retained')
            context['current_prompt'] = 'Report the operator test results for normal and empty names, including exact observed values and failures. Do not run commands.'
            context['terminal_output']['output'] = 'Operator test results: normal name returned'
            result = CodexRunner().run(root, context, print)
            self.assertEqual(result['status'], 'cannot_verify', result)
            self.assertEqual(result['prompt'], '')
            self.assertTrue(result['findings'])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_adaptive_policy_starts_with_requirements_only(self):
        with tempfile.TemporaryDirectory(prefix='ai-live-adaptive-smoke-') as directory:
            root = Path(directory)
            (root / 'README.md').write_text('Feature: add hello(name) in hello.py returning Hello followed by the name. Acceptance: normal and empty names. Confirm the design before edits.', encoding='utf-8')
            (root / 'hello.py').write_text('def hello(name):\n    pass\n', encoding='utf-8')
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = CodexRunner().run(root, {'mode': 'prompt', 'action': 'analyze',
                'problem_file': 'README.md', 'accepted_requirements': '', 'conversation': {'updates': []}}, print)
            session = PromptSession(root, 'README.md', 'smoke')
            session.accept(session.begin(), result)
            prompt = result['prompt'].lower()
            self.assertEqual(result['status'], 'ready', result)
            self.assertGreater(len(result['approach'].split()), 150, result['approach'])
            self.assertNotRegex(result['approach'].lower(), r'\b(codex|cli|prompts?|operator|state_\d+)\b')
            self.assertIn('hello', result['approach'].lower())
            self.assertIn('empty', result['approach'].lower())
            self.assertNotIn(result['prompt'], result['approach'])
            self.assertIn('state_1', prompt)
            self.assertRegex(prompt, r'(do not|never) run (?:any |terminal |shell )?commands')
            self.assertRegex(prompt, r'(do not|no) (?:edit|file changes)')
            self.assertIn('acceptance', prompt)
            self.assertIn('readme.md', prompt)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_real_prompt_analysis_and_conversation_change_leave_project_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='ai-live-prompt-smoke-') as directory:
            root = Path(directory)
            (root / 'README.md').write_text("Implement hello(name) in hello.py to return 'Hello ' + name. No tests need to run.", encoding='utf-8')
            (root / 'hello.py').write_text('def hello(name):\n    pass\n', encoding='utf-8')
            session = PromptSession(root, 'README.md', 'smoke')

            def contents():
                return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}

            before = contents()
            initial = CodexRunner().run(root, {'mode': 'prompt', 'action': 'analyze',
                'problem_file': 'README.md', 'accepted_requirements': '', 'conversation': {'updates': []}}, print)
            session.accept(session.begin(), initial)
            self.assertEqual(initial['status'], 'ready', initial)
            self.assertEqual(len(session.history), 1)
            self.assertEqual(contents(), before)
            # Simulated user execution, not a VS Code terminal-capture test.
            (root / 'hello.py').write_text('def hello(name):\n    return "Hello " + name\n', encoding='utf-8')
            before_review = contents()
            review = CodexRunner().run(root, {'mode': 'prompt', 'action': 'check_output',
                'problem_file': 'README.md', 'current_prompt': initial['prompt'], 'previous_guidance': initial,
                'accepted_requirements': '', 'conversation': {'revision': 1, 'updates': [
                    {'revision': 1, 'text': 'Also add goodbye(name) in hello.py returning exactly "Bye " + name.'}]},
                'terminal_output': {'command': 'codex', 'output': 'Implemented hello(name). No tests run.',
                                    'running': True, 'truncated': False, 'exit_code': None}}, print)
            session.accept(session.begin(), review)
            self.assertEqual(review['status'], 'ready', review)
            self.assertIn('goodbye', review['prompt'].lower())
            self.assertTrue(review['conversation_change'], review)
            self.assertEqual(contents(), before_review)

    def test_adaptive_policy_hands_verification_to_operator_after_diff(self):
        with tempfile.TemporaryDirectory(prefix='ai-live-adaptive-check-') as directory:
            root = Path(directory)
            (root / 'README.md').write_text('Implement hello(name) returning "Hello " + name. Acceptance: normal and empty names. The operator must run python -m unittest at the project root before completion. No documentation or submission changes are required.', encoding='utf-8')
            (root / 'hello.py').write_text('def hello(name):\n    return "Hello " + name\n', encoding='utf-8')
            (root / 'test_hello.py').write_text('import unittest\nfrom hello import hello\nclass HelloTests(unittest.TestCase):\n    def test_normal(self):\n        self.assertEqual(hello("Ada"), "Hello Ada")\n    def test_empty(self):\n        self.assertEqual(hello(""), "Hello ")\n', encoding='utf-8')
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            output = CodexRunner().run(root, {'mode': 'prompt', 'action': 'check_output',
                'problem_file': 'README.md', 'current_prompt': 'Use approved STATE_3. Edit only hello.py to return "Hello " + name. Do not run commands. Return the complete diff and stop.',
                'choices': [{'question': 'Approve the scoped implementation of hello.py?', 'answer': 'Approved'}],
                'previous_guidance': {'findings': 'STATE_3\nConfirmed: README.md acceptance requires normal and empty names; test_hello.py covers both. Decisions: operator approved a single return expression in hello.py. Unresolved: implementation and operator test results.'},
                'conversation': {'updates': []}, 'accepted_requirements': '',
                'terminal_output': {'command': 'codex', 'running': True, 'truncated': False, 'exit_code': None,
                    'output': 'Changed hello.py only. Diff:\n--- a/hello.py\n+++ b/hello.py\n@@ -1,2 +1,2 @@\n def hello(name):\n-    pass\n+    return "Hello " + name\nNo commands or tests were run.'}}, print)
            session = PromptSession(root, 'README.md', 'smoke')
            session.accept(session.begin(), output)
            self.assertEqual(output['status'], 'cannot_verify', output)
            self.assertEqual(output['prompt'], '')
            self.assertIn('python -m unittest', output['findings'])
            self.assertIn('root', output['findings'].lower())
            self.assertEqual(output['blocked'], '')
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

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
