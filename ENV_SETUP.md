# Environment Setup

AI-Live reads simple `KEY=VALUE` pairs from `.env` using `env_loader.py`.

## Quick Start

```powershell
Copy-Item .env.example .env
```

Set your OpenAI API key in `.env`.

## Required

| Variable | Description |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI key for manual analysis and Realtime answering. |

## Optional

| Variable | Description | Default |
| --- | --- | --- |
| `OPENAI_ANALYSIS_MODEL` | Manual analysis model. | `gpt-5.5` |
| `OPENAI_REALTIME_MODEL` | Realtime audio model. | `gpt-realtime-2.1-mini` |
| `SAMPLE_RATE` | PCM input rate. Other values are normalized to 24 kHz. | `24000` |
| `CHANNELS` | Audio channel count. Desktop audio is converted to mono. | `1` |
| `CHUNK_SIZE` | Desktop audio chunk size in samples. | `1024` |
| `OPENAI_VAD_SILENCE_MS` | Server VAD silence window before ending an interviewer turn. | `350` |
| `OPENAI_VAD_THRESHOLD` | Server VAD speech detection threshold. | `0.5` |
| `OPENAI_VAD_PREFIX_PADDING_MS` | Audio retained before detected speech begins. | `300` |
| `AUTO_ANSWER_LATENCY_LOG` | Print Realtime answer timing logs. | `false` |

## Runtime Flow

Desktop loopback PCM is streamed continuously to one OpenAI Realtime conversation. Server VAD identifies speech boundaries. When Auto-Answer is enabled, the app requests a text-only response and forces the model to call `update_visible_answer` with `append`, `reset`, or `no_update`.

The app does not configure `audio.input.transcription`, does not use a transcription deployment, and does not make a second auto-answer model request.

Realtime model diagnostics are enabled by default. Console lines prefixed with
`realtime_model` include request metadata, session acknowledgements, speech boundaries,
completed tool arguments/text, response status and status details, token usage, and
server errors. Match response IDs and `client_turn_id` to trace a request. In particular,
`response.done` distinguishes a completed `no_update` from a failed, cancelled, or
token-limited response. These logs contain generated answer/project-update content;
audio payloads and instructions (including resume context) are omitted. They do not
provide a transcript or the model's internal reasoning. Set
`OPENAI_REALTIME_MODEL_LOG=false` to disable them. Restart the app after changing it.

If the Realtime connection reports a model access error, set `OPENAI_REALTIME_MODEL` to a Realtime model available to your OpenAI project.

For faster turn completion, try:

```env
CHUNK_SIZE=1024
OPENAI_VAD_SILENCE_MS=250
OPENAI_VAD_THRESHOLD=0.5
OPENAI_VAD_PREFIX_PADDING_MS=300
AUTO_ANSWER_LATENCY_LOG=true
```

If normal pauses are split into separate turns, increase `OPENAI_VAD_SILENCE_MS` to `300` or `350`.

## Security

- Do not commit `.env`.
- Use `.env.example` for placeholders only.
- Rotate any key that appears in logs or generated artifacts.
