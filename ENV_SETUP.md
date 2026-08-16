# Environment Setup

AI-Live reads simple `KEY=VALUE` pairs from `.env` using `env_loader.py`.

## Quick Start

```powershell
Copy-Item .env.example .env
```

Edit `.env` and fill in the Azure OpenAI values. The Realtime session uses its own strict credentials and does not fall back to legacy transcription or shared analysis variables.

## Required

| Variable | Description |
| --- | --- |
| `AZURE_OPENAI_ANALYSIS_API_KEY` | Azure OpenAI key for manual Text, Code, General, and Screenshot analysis. |
| `AZURE_OPENAI_ANALYSIS_ENDPOINT` | Azure endpoint for the manual-analysis resource. |
| `AZURE_OPENAI_REALTIME_API_KEY` | Azure OpenAI key for the direct audio Realtime deployment. |
| `AZURE_OPENAI_REALTIME_ENDPOINT` | Azure endpoint that hosts the Realtime deployment. |
| `AZURE_OPENAI_REALTIME_DEPLOYMENT` | Deployment used as the Realtime session model. Set this to `gpt-realtime-2.1-mini`. |

## Optional

| Variable | Description | Default |
| --- | --- | --- |
| `AZURE_OPENAI_ANALYSIS_DEPLOYMENT` | Deployment name for manual analysis. | `gpt-5.5` |
| `AZURE_OPENAI_API_KEY` | Shared fallback used only by manual analysis. | Empty |
| `AZURE_OPENAI_ENDPOINT` | Shared endpoint fallback used only by manual analysis. | Empty |
| `SAMPLE_RATE` | PCM input rate. Other values are normalized to 24 kHz. | `24000` |
| `CHANNELS` | Audio channel count. Desktop audio is converted to mono. | `1` |
| `CHUNK_SIZE` | Desktop audio chunk size in samples. | `1024` |
| `AZURE_OPENAI_VAD_SILENCE_MS` | Server VAD silence window before ending an interviewer turn. | `350` |
| `AZURE_OPENAI_VAD_THRESHOLD` | Server VAD speech detection threshold. | `0.5` |
| `AZURE_OPENAI_VAD_PREFIX_PADDING_MS` | Audio retained before detected speech begins. | `300` |
| `AUTO_ANSWER_LATENCY_LOG` | Print Realtime answer timing logs. | `false` |

## Runtime Flow

Desktop loopback PCM is streamed continuously to one Azure OpenAI Realtime conversation. Server VAD identifies speech boundaries. When Auto-Answer is enabled, the app requests a text-only response and forces the model to call `update_visible_answer` with `append`, `reset`, or `no_update`.

The app does not configure `audio.input.transcription`, does not use a transcription deployment, and does not make a second auto-answer model request.

If Azure returns `OperationNotSupported` during the WebSocket handshake, the configured key/endpoint points to a resource that does not host a compatible Realtime deployment. Create or select the `gpt-realtime-2.1-mini` deployment in Azure and use that resource's key and endpoint; changing only the local deployment string cannot add the model to a resource.

For faster turn completion, try:

```env
CHUNK_SIZE=1024
AZURE_OPENAI_VAD_SILENCE_MS=250
AZURE_OPENAI_VAD_THRESHOLD=0.5
AZURE_OPENAI_VAD_PREFIX_PADDING_MS=300
AUTO_ANSWER_LATENCY_LOG=true
```

If normal pauses are split into separate turns, increase `AZURE_OPENAI_VAD_SILENCE_MS` to `300` or `350`.

## Security

- Do not commit `.env`.
- Use `.env.example` for placeholders only.
- Rotate any key that appears in logs or generated artifacts.
