# Environment Setup

AI-Live reads simple `KEY=VALUE` pairs from `.env` using `env_loader.py`.

## Quick Start

```powershell
Copy-Item .env.example .env
```

Edit `.env` and fill in your Azure OpenAI values. The app supports separate Azure keys and endpoints for each model path.

## Required

| Variable | Description |
| --- | --- |
| `AZURE_OPENAI_ANALYSIS_API_KEY` | Azure OpenAI API key for the `gpt-5.5` analysis deployment. |
| `AZURE_OPENAI_ANALYSIS_ENDPOINT` | Azure OpenAI endpoint for the analysis resource. |
| `AZURE_OPENAI_AUTO_ANSWER_API_KEY` | Azure OpenAI API key for the `gpt-5.4-nano` auto-answer deployment. |
| `AZURE_OPENAI_AUTO_ANSWER_ENDPOINT` | Azure OpenAI endpoint for the auto-answer resource. |
| `AZURE_OPENAI_TRANSCRIPTION_API_KEY` | Azure OpenAI API key for the realtime transcription resource. |
| `AZURE_OPENAI_TRANSCRIPTION_ENDPOINT` | Azure OpenAI endpoint for the realtime transcription resource. |

## Optional

| Variable | Description | Default |
| --- | --- | --- |
| `AZURE_OPENAI_API_KEY` | Shared fallback API key used only when a purpose-specific key is omitted. | Empty |
| `AZURE_OPENAI_ENDPOINT` | Shared fallback endpoint used only when a purpose-specific endpoint is omitted. | Empty |
| `AZURE_OPENAI_REALTIME_DEPLOYMENT` | Azure deployment name for the GPT realtime WebSocket session. | `gpt-realtime` |
| `AZURE_OPENAI_TRANSCRIPTION_MODEL` | Transcription model configured inside the realtime session. | `whisper-1` |
| `AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT` | Legacy alias for `AZURE_OPENAI_REALTIME_DEPLOYMENT`. | Empty |
| `AZURE_OPENAI_ANALYSIS_DEPLOYMENT` | Azure deployment name for manual analysis tasks. | `gpt-5.5` |
| `AZURE_OPENAI_AUTO_ANSWER_DEPLOYMENT` | Azure deployment name for live desktop auto-answer suggestions. | `gpt-5.4-nano` |
| `SAMPLE_RATE` | PCM input sample rate in Hz. Values other than `24000` are normalized at runtime. | `24000` |
| `CHANNELS` | Number of audio channels. Invalid values fall back safely. | `1` |
| `CHUNK_SIZE` | Audio chunk size in samples. Invalid values fall back safely. | `1024` |

## Security

- Do not commit `.env`.
- Use `.env.example` for placeholders only.
- Delete generated build/debug artifacts if they contain environment snapshots.
- Rotate API keys if they appeared in a generated artifact or shared log.
