# Environment Setup

AI-Live reads simple `KEY=VALUE` pairs from `.env` using `env_loader.py`.

## Quick Start

```powershell
Copy-Item .env.example .env
```

Edit `.env` and fill in your values.

## Required

| Variable | Description |
| --- | --- |
| `GEMINI_API` | Google Gemini API key used for live transcription and manual analysis. |

## Optional

| Variable | Description | Default |
| --- | --- | --- |
| `DEEPSEEK` | OpenRouter API key used only by optional DeepSeek helper functions. `OPENROUTER_API_KEY` is also accepted as a fallback. | Empty |
| `GEMINI_FLASH_MODEL` | Gemini model for standard/manual chat analysis. | `gemini-2.5-pro` |
| `GEMINI_GENERAL_MODEL` | Gemini model for the General Analysis button. | `gemini-2.0-flash` |
| `GEMINI_LIVE_MODEL` | Gemini Live model for transcription. | `gemini-3.1-flash-live-preview` |
| `DEEPSEEK_MODEL` | DeepSeek/OpenRouter model identifier. | `tngtech/deepseek-r1t-chimera:free` |
| `SAMPLE_RATE` | Gemini Live PCM input sample rate in Hz. Values other than `16000` are normalized at runtime. | `16000` |
| `CHANNELS` | Number of audio channels. Invalid values fall back safely. | `1` |
| `CHUNK_SIZE` | Audio chunk size in samples. Invalid values fall back safely. | `1024` |

## Security

- Do not commit `.env`.
- Use `.env.example` for placeholders only.
- Delete generated build/debug artifacts if they contain environment snapshots.
- Rotate API keys if they appeared in a generated artifact or shared log.

`gemini-live-2.5-flash-preview` is treated as a stale legacy value at runtime and is automatically replaced with the current default.
`SAMPLE_RATE=48000` is also treated as stale for Gemini Live input and is normalized to `16000`.
