import io
import json
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch
from tests.test_project_guide import result
from pathlib import Path
from project_guide.runner import build_command, parse_events, CodexRunner
from project_guide.mcp import dispatch
from project_guide.files import ProjectFiles, GuideError


class RunnerTests(unittest.TestCase):
    def test_prompt_request_uses_prompt_contract_and_one_prompt_instructions(self):
        from tests.test_prompt_guide import response
        captured = {}

        class Process:
            returncode = 0

            def __init__(self, args, **kwargs):
                captured['schema'] = json.loads(Path(args[args.index('--output-schema') + 1]).read_text())

            def communicate(self, instructions, timeout):
                captured['instructions'] = instructions
                return '\n'.join(json.dumps(e) for e in [
                    {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(response())}},
                    {'type': 'turn.completed'}]), ''

        with tempfile.TemporaryDirectory() as directory, patch('project_guide.runner.codex_command', return_value=['codex']), patch('project_guide.runner.subprocess.Popen', Process):
            output = CodexRunner().run(directory, {'mode': 'prompt', 'action': 'analyze'})
        self.assertEqual(output['prompt'], 'Implement the greeting')
        self.assertIn('prompt', captured['schema']['properties'])
        self.assertNotIn('steps', captured['schema']['properties'])
        self.assertIn('exactly one', captured['instructions'])
        self.assertNotIn('Every step must include diff', captured['instructions'])

    def test_answer_is_returned_without_file_checks_or_repair(self):
        data = result()
        data['steps'][0].update(path='missing.py', anchor='not saved', line=999)
        runner = CodexRunner()
        with patch.object(runner, '_run_once', return_value=data) as call:
            output = runner.run('not-an-existing-directory', {'action': 'analyze'})
        self.assertIs(output, data)
        self.assertEqual(call.call_count, 1)
        self.assertNotIn('location_repair', call.call_args.args[1])

    def test_cancel_terminates_a_running_process(self):
        runner = CodexRunner()
        runner.process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.addCleanup(lambda: runner.process.kill() if runner.process.poll() is None else None)
        runner.cancel()
        runner.process.wait(timeout=5)
        self.assertTrue(runner.cancelled.is_set())

    def test_command_uses_yolo_and_keeps_guide_tool_restrictions(self):
        args = build_command(['codex.exe'], Path('C:/project'), Path('C:/schema.json'), ['python', '-m', 'project_guide.mcp'])
        for option in ['--yolo', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--json']:
            self.assertIn(option, args)
        self.assertIn('approval_policy="never"', args)
        self.assertIn('features.shell_tool=false', args)
        self.assertIn('features.apply_patch_freeform=false', args)
        self.assertNotIn('--sandbox', args)
        self.assertNotIn('windows.sandbox="unelevated"', args)

    def test_parse_events_only_uses_complete_final_message(self):
        lines = '\n'.join(json.dumps(e) for e in [
            {'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'ignore'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"summary":"ok"}'}},
            {'type': 'turn.completed'},
        ])
        self.assertEqual(parse_events(lines)['summary'], 'ok')
        with self.assertRaises(GuideError):
            parse_events(lines + '\n' + json.dumps({'type': 'turn.failed', 'error': {'message': 'failed'}}))

    def test_mcp_only_exposes_read_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'a.txt').write_text('hello')
            files = ProjectFiles(directory)
            tools = dispatch(files, 'tools/list', {})['tools']
            self.assertEqual({t['name'] for t in tools}, {'list_files', 'read_file', 'search_text'})
            out = dispatch(files, 'tools/call', {'name': 'read_file', 'arguments': {'path': 'a.txt'}})
            self.assertIn('hello', out['content'][0]['text'])
            with self.assertRaises(GuideError):
                dispatch(files, 'tools/call', {'name': 'execute', 'arguments': {'command': 'anything'}})
