import json
import os
import asyncio
import unittest
from unittest.mock import patch

import azure_realtime


class FakeWebSocket:
    def __init__(self):
        self.messages = []
        self.closed = False

    async def send(self, payload):
        self.messages.append(json.loads(payload))

    async def close(self):
        self.closed = True


class AzureRealtimeConfigTests(unittest.TestCase):
    def test_vad_env_parsers_use_defaults_for_missing_or_invalid_values(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(azure_realtime.parse_int_env("AZURE_OPENAI_VAD_SILENCE_MS", 350), 350)
            self.assertEqual(azure_realtime.parse_float_env("AZURE_OPENAI_VAD_THRESHOLD", 0.5), 0.5)

        with patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_VAD_SILENCE_MS": "-1",
                "AZURE_OPENAI_VAD_THRESHOLD": "bad",
            },
            clear=True,
        ):
            self.assertEqual(azure_realtime.parse_int_env("AZURE_OPENAI_VAD_SILENCE_MS", 350), 350)
            self.assertEqual(azure_realtime.parse_float_env("AZURE_OPENAI_VAD_THRESHOLD", 0.5), 0.5)

    def test_realtime_url_uses_only_realtime_endpoint(self):
        with patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_REALTIME_ENDPOINT": "https://realtime-resource.openai.azure.com",
                "AZURE_OPENAI_TRANSCRIPTION_ENDPOINT": "https://wrong-resource.openai.azure.com",
            },
            clear=True,
        ):
            url = azure_realtime._realtime_url("gpt-realtime-2.1-mini")

        self.assertEqual(
            url,
            "wss://realtime-resource.openai.azure.com/openai/v1/realtime?model=gpt-realtime-2.1-mini",
        )

    def test_realtime_session_does_not_fall_back_to_legacy_credentials(self):
        with patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_TRANSCRIPTION_API_KEY": "legacy-key",
                "AZURE_OPENAI_TRANSCRIPTION_ENDPOINT": "https://legacy.openai.azure.com",
                "AZURE_OPENAI_REALTIME_DEPLOYMENT": "gpt-realtime-2.1-mini",
            },
            clear=True,
        ):
            session = azure_realtime.AzureRealtimeAnswerSession()

        self.assertIsNone(session.api_key)
        self.assertIsNone(session.url)

    def test_answer_update_validation(self):
        self.assertEqual(
            azure_realtime.validate_answer_update('{"action":"append","text":" More detail. "}'),
            ("append", "More detail."),
        )
        self.assertEqual(
            azure_realtime.validate_answer_update({"action": "no_update", "text": ""}),
            ("no_update", ""),
        )
        for payload in (
            "not-json",
            {"action": "append", "text": ""},
            {"action": "no_update", "text": "unexpected"},
            {"action": "unknown", "text": "answer"},
            {"action": "reset", "text": "answer", "extra": True},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                azure_realtime.validate_answer_update(payload)


class AzureRealtimeProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_REALTIME_API_KEY": "test-key",
                "AZURE_OPENAI_REALTIME_ENDPOINT": "https://test-resource.openai.azure.com",
                "AZURE_OPENAI_REALTIME_DEPLOYMENT": "gpt-realtime-2.1-mini",
            },
            clear=False,
        )
        self.env_patch.start()
        self.deployment_patch = patch.object(
            azure_realtime,
            "REALTIME_DEPLOYMENT",
            "gpt-realtime-2.1-mini",
        )
        self.deployment_patch.start()

    def tearDown(self):
        self.deployment_patch.stop()
        self.env_patch.stop()

    def make_session(self, updates=None, statuses=None):
        update_target = updates if updates is not None else []
        session = azure_realtime.AzureRealtimeAnswerSession(
            answer_update_callback=lambda action, text: update_target.append((action, text)),
            status_callback=(lambda status, color: statuses.append((status, color))) if statuses is not None else None,
            instructions_provider=lambda: "test interview instructions",
        )
        session.websocket = FakeWebSocket()
        return session

    async def test_session_config_is_text_only_audio_conversation_with_forced_tool(self):
        session = self.make_session()
        await session.configure_session()

        event = session.websocket.messages[-1]
        config = event["session"]
        self.assertEqual(config["model"], "gpt-realtime-2.1-mini")
        self.assertEqual(config["output_modalities"], ["text"])
        self.assertEqual(config["audio"]["input"]["format"], {"type": "audio/pcm", "rate": 24000})
        self.assertFalse(config["audio"]["input"]["turn_detection"]["create_response"])
        self.assertNotIn("transcription", config["audio"]["input"])
        self.assertEqual(config["tools"], [azure_realtime.ANSWER_UPDATE_TOOL])
        self.assertEqual(
            config["tool_choice"],
            {"type": "function", "name": "update_visible_answer"},
        )

    async def test_speech_stop_only_requests_answer_when_enabled(self):
        session = self.make_session()
        await session.handle_server_event(
            {"type": "input_audio_buffer.speech_stopped", "item_id": "audio-1"}
        )
        self.assertEqual(session.websocket.messages, [])

        session.auto_answer_enabled = True
        await session.handle_server_event(
            {"type": "input_audio_buffer.speech_stopped", "item_id": "audio-2"}
        )
        self.assertEqual(
            [message["type"] for message in session.websocket.messages],
            ["session.update", "response.create"],
        )
        response = session.websocket.messages[-1]["response"]
        self.assertEqual(response["output_modalities"], ["text"])
        self.assertEqual(response["tool_choice"]["name"], "update_visible_answer")

    async def test_audio_still_streams_while_auto_answer_is_disabled(self):
        session = self.make_session()
        session.running = True
        session.auto_answer_enabled = False
        session.audio_queue = asyncio.Queue()
        await session.audio_queue.put(b"\x01\x02")

        task = asyncio.create_task(session.send_audio_to_azure())
        for _ in range(10):
            if session.websocket.messages:
                break
            await asyncio.sleep(0)
        session.running = False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        self.assertEqual(session.websocket.messages[0]["type"], "input_audio_buffer.append")
        self.assertNotIn("response.create", [message["type"] for message in session.websocket.messages])

    async def test_completed_function_call_is_applied_and_acknowledged_without_followup(self):
        updates = []
        session = self.make_session(updates)
        session.auto_answer_enabled = True
        session._current_turn_token = "turn-1"
        session._response_turns["resp-1"] = "turn-1"

        await session.handle_server_event(
            {
                "type": "response.function_call_arguments.delta",
                "response_id": "resp-1",
                "call_id": "call-1",
                "delta": '{"action":"append",',
            }
        )
        await session.handle_server_event(
            {
                "type": "response.function_call_arguments.delta",
                "response_id": "resp-1",
                "call_id": "call-1",
                "delta": '"text":"Only the continuation."}',
            }
        )
        await session.handle_server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "resp-1",
                "call_id": "call-1",
                "name": "update_visible_answer",
                "arguments": "",
            }
        )

        self.assertEqual(updates, [("append", "Only the continuation.")])
        self.assertEqual([message["type"] for message in session.websocket.messages], ["conversation.item.create"])
        output = json.loads(session.websocket.messages[0]["item"]["output"])
        self.assertEqual(output, {"status": "applied", "action": "append"})

    async def test_invalid_call_retries_once_without_updating_ui(self):
        updates = []
        statuses = []
        session = self.make_session(updates, statuses)
        session.auto_answer_enabled = True
        session._current_turn_token = "turn-1"
        session._response_turns["resp-1"] = "turn-1"
        session._retry_counts["turn-1"] = 0

        await session.handle_server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "resp-1",
                "call_id": "call-1",
                "name": "update_visible_answer",
                "arguments": '{"action":"append","text":""}',
            }
        )
        await session.handle_server_event(
            {
                "type": "response.done",
                "response": {"id": "resp-1", "status": "completed"},
            }
        )

        response_creates = [m for m in session.websocket.messages if m["type"] == "response.create"]
        self.assertEqual(updates, [])
        self.assertEqual(len(response_creates), 1)
        self.assertEqual(response_creates[0]["response"]["metadata"]["attempt"], "1")

        session._response_turns["resp-2"] = "turn-1"
        await session.handle_server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "resp-2",
                "call_id": "call-2",
                "name": "update_visible_answer",
                "arguments": "not-json",
            }
        )
        await session.handle_server_event(
            {
                "type": "response.done",
                "response": {"id": "resp-2", "status": "completed"},
            }
        )

        response_creates = [m for m in session.websocket.messages if m["type"] == "response.create"]
        self.assertEqual(len(response_creates), 1)
        self.assertIn(("Answer unavailable", "#FF0000"), statuses)

    async def test_new_speech_cancels_and_stale_function_call_is_ignored(self):
        updates = []
        session = self.make_session(updates)
        session.auto_answer_enabled = True
        session._current_turn_token = "turn-1"
        session._active_response_id = "resp-1"
        session._response_turns["resp-1"] = "turn-1"

        await session.handle_server_event(
            {"type": "input_audio_buffer.speech_started", "item_id": "audio-2"}
        )
        await session.handle_server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "resp-1",
                "call_id": "call-1",
                "name": "update_visible_answer",
                "arguments": '{"action":"reset","text":"Stale answer"}',
            }
        )

        self.assertEqual(updates, [])
        self.assertEqual(
            session.websocket.messages[0],
            {"type": "response.cancel", "response_id": "resp-1"},
        )

    async def test_context_reset_closes_session_and_discards_pending_state_and_audio(self):
        session = self.make_session([])
        session.audio_queue = asyncio.Queue()
        await session.audio_queue.put(b"old audio")
        session._current_turn_token = "turn-1"
        session._active_response_id = "resp-1"
        session._response_turns["resp-1"] = "turn-1"

        await session._reset_connection()

        self.assertTrue(session.websocket.closed)
        self.assertTrue(session.audio_queue.empty())
        self.assertIsNone(session._current_turn_token)
        self.assertEqual(session._response_turns, {})

    async def test_successful_unexpected_reconnect_notifies_the_ui_to_clear_context(self):
        resets = []
        session = azure_realtime.AzureRealtimeAnswerSession(
            session_reset_callback=lambda: resets.append(True),
            instructions_provider=lambda: "instructions",
        )
        connections = [FakeWebSocket(), FakeWebSocket()]
        connection_runs = 0

        async def fake_connect(_url, _api_key):
            return connections.pop(0)

        async def fake_run_connection():
            nonlocal connection_runs
            connection_runs += 1
            if connection_runs == 2:
                session.running = False

        async def no_delay(_seconds):
            return None

        session.running = True
        with (
            patch("azure_realtime._connect_websocket", side_effect=fake_connect),
            patch.object(session, "_run_connection", side_effect=fake_run_connection),
            patch("azure_realtime.asyncio.sleep", side_effect=no_delay),
        ):
            await session.run()

        self.assertEqual(resets, [True])

    async def test_freeform_text_is_treated_as_protocol_error_and_retried(self):
        session = self.make_session([])
        session.auto_answer_enabled = True
        session._current_turn_token = "turn-1"
        session._response_turns["resp-1"] = "turn-1"
        session._retry_counts["turn-1"] = 0

        await session.handle_server_event(
            {
                "type": "response.output_text.delta",
                "response_id": "resp-1",
                "delta": "Unexpected answer",
            }
        )
        await session.handle_server_event(
            {
                "type": "response.done",
                "response": {"id": "resp-1", "status": "completed"},
            }
        )

        response_creates = [m for m in session.websocket.messages if m["type"] == "response.create"]
        self.assertEqual(len(response_creates), 1)
        self.assertEqual(response_creates[0]["response"]["metadata"]["attempt"], "1")


if __name__ == "__main__":
    unittest.main()
