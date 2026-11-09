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

class ProjectExtractionTests(unittest.IsolatedAsyncioTestCase):
    setUp = AzureRealtimeProtocolTests.setUp
    tearDown = AzureRealtimeProtocolTests.tearDown
    make_session = AzureRealtimeProtocolTests.make_session

    async def start_project_response(self):
        from project_guide.conversation import ProjectUpdateStore
        session = self.make_session()
        session.project_update_store = ProjectUpdateStore()
        session.project_update_store.activate('project-a')
        session.auto_answer_enabled = True
        await session.handle_server_event({'type': 'input_audio_buffer.speech_stopped'})
        metadata = session.websocket.messages[-1]['response']['metadata']
        await session.handle_server_event({'type': 'response.created', 'response': {
            'id': 'r', 'metadata': metadata}})
        return session

    async def send_update(self, session, **overrides):
        payload = {'action': 'no_update', 'text': '', 'project_update': 'Use SQLite.'}
        payload.update(overrides)
        await session.handle_server_event({'type': 'response.function_call_arguments.done',
            'response_id': 'r', 'call_id': 'c', 'name': 'update_visible_answer',
            'arguments': json.dumps(payload)})

    async def finish(self, session, status='completed'):
        await session.handle_server_event({'type': 'response.done',
            'response': {'id': 'r', 'status': status}})

    async def test_project_field_validation_preserves_pair_api(self):
        self.assertEqual(azure_realtime.validate_answer_update({
            'action': 'no_update', 'text': '', 'project_update': 'Use SQLite.'}), ('no_update', ''))
        for value in [None, 42, [], {}]:
            with self.assertRaises(ValueError):
                azure_realtime.validate_answer_update({'action': 'no_update', 'text': '', 'project_update': value})

    async def test_no_update_records_only_after_success(self):
        session = await self.start_project_response()
        await self.send_update(session)
        self.assertEqual(session.project_update_store.snapshot('project-a')['updates'], [])
        await self.finish(session)
        self.assertEqual(session.project_update_store.snapshot('project-a')['updates'],
                         [{'revision': 1, 'text': 'Use SQLite.'}])
        await self.finish(session)
        self.assertEqual(session.project_update_store.snapshot('project-a')['revision'], 1)

    async def test_failed_cancelled_invalid_disabled_and_stale_responses_do_not_record(self):
        for case in ['failed', 'cancelled', 'invalid', 'disabled', 'stale', 'freeform']:
            with self.subTest(case=case):
                session = await self.start_project_response()
                if case == 'invalid':
                    await self.send_update(session, action='append')
                else:
                    await self.send_update(session)
                if case == 'disabled':
                    session.auto_answer_enabled = False
                if case == 'stale':
                    session.project_update_store.activate('project-b')
                if case == 'freeform':
                    await session.handle_server_event({'type': 'response.output_text.delta',
                                                       'response_id': 'r', 'delta': 'bad'})
                await self.finish(session, case if case in ['failed', 'cancelled'] else 'completed')
                self.assertEqual(session.project_update_store.snapshot('project-a')['updates'], [])
                self.assertEqual(session.project_update_store.snapshot('project-b')['updates'], [])

    async def test_selection_changes_before_created_event_do_not_rebind(self):
        session = await self.start_project_response()
        session.project_update_store.activate('project-b')
        await session.handle_server_event({'type': 'response.created', 'response': {'id': 'r'}})
        await self.send_update(session)
        await self.finish(session)
        self.assertEqual(session.project_update_store.snapshot('project-b')['updates'], [])

    async def test_retry_keeps_original_project_binding(self):
        session = await self.start_project_response()
        await self.send_update(session, action='append')
        session.project_update_store.activate('project-b')
        await self.finish(session)
        metadata = session.websocket.messages[-1]['response']['metadata']
        await session.handle_server_event({'type': 'response.created', 'response': {
            'id': 'r2', 'metadata': metadata}})
        await session.handle_server_event({'type': 'response.function_call_arguments.done',
            'response_id': 'r2', 'call_id': 'c2', 'name': 'update_visible_answer',
            'arguments': json.dumps({'action': 'no_update', 'text': '', 'project_update': 'Use SQLite.'})})
        await session.handle_server_event({'type': 'response.done', 'response': {'id': 'r2', 'status': 'completed'}})
        self.assertEqual(session.project_update_store.snapshot('project-b')['updates'], [])

    async def test_legacy_and_empty_updates_never_infer_from_answer(self):
        for extra in [{}, {'project_update': ''}]:
            session = await self.start_project_response()
            updates = []
            session.answer_update_callback = lambda action, text: updates.append((action, text))
            await session.handle_server_event({'type': 'response.function_call_arguments.done',
                'response_id': 'r', 'call_id': 'c', 'name': 'update_visible_answer',
                'arguments': json.dumps({'action': 'reset', 'text': 'I propose Redis.', **extra})})
            await self.finish(session)
            self.assertEqual(updates, [('reset', 'I propose Redis.')])
            self.assertEqual(session.project_update_store.snapshot('project-a')['updates'], [])

    async def test_new_speech_before_success_discards_pending_update(self):
        session = await self.start_project_response()
        await self.send_update(session)
        await session.handle_server_event({'type': 'input_audio_buffer.speech_started'})
        await self.finish(session)
        self.assertEqual(session.project_update_store.snapshot('project-a')['updates'], [])

    async def test_selection_switch_during_request_await_does_not_rebind(self):
        session = await self.start_project_response()
        await self.finish(session, 'cancelled')
        async def switch_selection():
            session.project_update_store.activate('project-b')
        with patch.object(session, 'configure_session', side_effect=switch_selection):
            await session.handle_server_event({'type': 'input_audio_buffer.speech_stopped'})
        metadata = session.websocket.messages[-1]['response']['metadata']
        await session.handle_server_event({'type': 'response.created', 'response': {'id': 'r', 'metadata': metadata}})
        await self.send_update(session)
        await self.finish(session)
        self.assertEqual(session.project_update_store.snapshot('project-b')['updates'], [])

    async def test_second_distinct_tool_call_invalidates_project_update(self):
        session = await self.start_project_response()
        await self.send_update(session)
        await session.handle_server_event({'type': 'response.function_call_arguments.done',
            'response_id': 'r', 'call_id': 'other', 'name': 'update_visible_answer',
            'arguments': json.dumps({'action': 'no_update', 'text': '', 'project_update': 'Use Redis.'})})
        await self.finish(session)
        self.assertEqual(session.project_update_store.snapshot('project-a')['updates'], [])

    async def test_malformed_action_is_validation_error(self):
        for action in [[], {}]:
            with self.assertRaises(ValueError):
                azure_realtime.validate_answer_update({'action': action, 'text': '', 'project_update': 'x'})

    async def test_speech_start_binds_project_before_selection_changes(self):
        for initial in ['project-a', '']:
            for switch_during_cancel in [False, True]:
                with self.subTest(initial=initial, during_cancel=switch_during_cancel):
                    session = await self.start_project_response()
                    if not initial:
                        session.project_update_store.clear()
                    original_cancel = session._cancel_current_response

                    async def cancel_and_switch():
                        session.project_update_store.activate('project-b')
                        await original_cancel()

                    if switch_during_cancel:
                        with patch.object(session, '_cancel_current_response', side_effect=cancel_and_switch):
                            await session.handle_server_event({'type': 'input_audio_buffer.speech_started'})
                    else:
                        await session.handle_server_event({'type': 'input_audio_buffer.speech_started'})
                        session.project_update_store.activate('project-b')
                    await session.handle_server_event({'type': 'input_audio_buffer.speech_stopped'})
                    metadata = session.websocket.messages[-1]['response']['metadata']
                    await session.handle_server_event({'type': 'response.created', 'response': {
                        'id': 'new', 'metadata': metadata}})
                    await session.handle_server_event({'type': 'response.function_call_arguments.done',
                        'response_id': 'new', 'call_id': 'new-call', 'name': 'update_visible_answer',
                        'arguments': json.dumps({'action': 'no_update', 'text': '', 'project_update': 'Use SQLite.'})})
                    await session.handle_server_event({'type': 'response.done',
                        'response': {'id': 'new', 'status': 'completed'}})
                    self.assertEqual(session.project_update_store.snapshot('project-b')['updates'], [])

    async def test_mismatched_request_context_drops_update_even_if_selection_returns(self):
        session = await self.start_project_response()
        await self.finish(session, 'cancelled')
        await session.handle_server_event({'type': 'input_audio_buffer.speech_started'})

        async def configure_other_project():
            session.project_update_store.activate('project-b')

        with patch.object(session, 'configure_session', side_effect=configure_other_project):
            await session.handle_server_event({'type': 'input_audio_buffer.speech_stopped'})
        metadata = session.websocket.messages[-1]['response']['metadata']
        session.project_update_store.activate('project-a')
        await session.handle_server_event({'type': 'response.created', 'response': {'id': 'r', 'metadata': metadata}})
        await self.send_update(session)
        await self.finish(session)
        self.assertEqual(session.project_update_store.snapshot('project-a')['updates'], [])

    async def test_unchanged_project_from_speech_start_records_update(self):
        session = await self.start_project_response()
        await self.finish(session, 'cancelled')
        await session.handle_server_event({'type': 'input_audio_buffer.speech_started'})
        await session.handle_server_event({'type': 'input_audio_buffer.speech_stopped'})
        metadata = session.websocket.messages[-1]['response']['metadata']
        await session.handle_server_event({'type': 'response.created', 'response': {'id': 'r', 'metadata': metadata}})
        await self.send_update(session)
        await self.finish(session)
        self.assertEqual(session.project_update_store.snapshot('project-a')['revision'], 1)


if __name__ == "__main__":
    unittest.main()
