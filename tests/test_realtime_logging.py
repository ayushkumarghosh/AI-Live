import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

import azure_realtime


class RealtimeLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_completion_logs_status_output_and_usage(self):
        with patch.dict(os.environ, {"AZURE_OPENAI_REALTIME_MODEL_LOG": "true"}):
            session = azure_realtime.AzureRealtimeAnswerSession()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                await session.handle_server_event({"type": "response.done", "response": {
                    "id": "resp-diagnostic", "status": "incomplete",
                    "status_details": {"reason": "max_output_tokens"},
                    "usage": {"output_tokens": 2048},
                    "output": [{"type": "function_call", "arguments":
                               json.dumps({"action": "no_update", "text": ""})}],
                }})
        log = output.getvalue()
        for expected in ("realtime_model", "resp-diagnostic", "max_output_tokens",
                         "output_tokens", "no_update"):
            self.assertIn(expected, log)

    async def test_request_logging_omits_instructions_and_audio(self):
        class Socket:
            async def send(self, payload):
                pass

        with patch.dict(os.environ, {"AZURE_OPENAI_REALTIME_MODEL_LOG": "true"}):
            session = azure_realtime.AzureRealtimeAnswerSession()
            session.websocket = Socket()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                await session.configure_session()
                await session._send_event({"type": "response.create", "response": {
                    "instructions": "PRIVATE RESUME", "metadata": {"client_turn_id": "turn-7"}}})
                await session._send_event({"type": "input_audio_buffer.append", "audio": "PRIVATE PCM"})
        log = output.getvalue()
        self.assertIn("turn-7", log)
        self.assertIn("session.update", log)
        self.assertNotIn("PRIVATE", log)
        self.assertNotIn("input_audio_buffer.append", log)
        self.assertNotIn("You are a realtime", log)

    async def test_logging_can_be_disabled(self):
        with patch.dict(os.environ, {"AZURE_OPENAI_REALTIME_MODEL_LOG": "false"}):
            session = azure_realtime.AzureRealtimeAnswerSession()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                await session.handle_server_event({"type": "session.created", "session": {"id": "hidden"}})
        self.assertEqual(output.getvalue(), "")
