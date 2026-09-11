import tempfile
import unittest
from pathlib import Path
from project_guide.context import publish, get_project_guide_context_section
from project_guide.session import GuideSession
from azure_realtime import build_realtime_answer_instructions, AzureRealtimeAnswerSession


class GuideContextTests(unittest.TestCase):
    def tearDown(self):
        publish(None)

    def test_realtime_response_reads_latest_context_and_removes_cleared_context(self):
        audio = AzureRealtimeAnswerSession(instructions_provider=lambda:
            build_realtime_answer_instructions('', get_project_guide_context_section()))
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('Implement a queue')
            publish(GuideSession(directory, 'README.md', 'one'))
            self.assertIn('Implement a queue', audio._session_update_event()['session']['instructions'])
            self.assertIn('Implement a queue', audio._response_create_event('turn', 0)['response']['instructions'])
            publish(None)
            self.assertNotIn('PROJECT GUIDE CONTEXT', audio._response_create_event('turn', 0)['response']['instructions'])

    def test_audio_instructions_include_resume_and_bounded_problem(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('Problem text ' * 10000)
            session = GuideSession(directory, 'README.md', 'one')
            session.choices.append({'question': 'Language?', 'answer': 'Python'})
            publish(session)
            section = get_project_guide_context_section()
            self.assertIn('[truncated]', section)
            self.assertIn('Python', section)
            self.assertLess(len(section), 10000)
            instructions = build_realtime_answer_instructions('Resume experience', section)
            self.assertIn('Resume experience', instructions)
            self.assertIn('PROJECT GUIDE CONTEXT', instructions)
            self.assertIn('Problem text', instructions)
            self.assertFalse(publish(session))
