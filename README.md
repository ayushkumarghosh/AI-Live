# AI-Live

AI-Live is a Windows desktop interview overlay. It streams desktop loopback audio directly to Azure OpenAI `gpt-realtime-2.1-mini`, receives text answers from the same Realtime conversation, and keeps related answer continuations together in the UI.

## Features

- Direct desktop audio → Azure OpenAI Realtime → text-answer flow
- Server VAD for interviewer turn detection
- Continuation-aware visible answers:
  - related follow-ups append a new paragraph
  - same-topic corrections append without rewriting earlier text
  - new topics replace the visible answer
  - acknowledgements and filler leave the answer unchanged
- Automatic cancellation when new interviewer speech starts
- Resume PDF context refreshed into the Realtime instructions
- Manual Text Input, Screenshot, Code Analysis, and General Analysis using Azure OpenAI `gpt-5.5`
- Transparent, draggable PyQt6 overlay excluded from screen capture on supported Windows versions

## Architecture

- `ai_live.py` starts the overlay, desktop audio manager, and manual-analysis handlers.
- `live_transcription.py` captures desktop loopback PCM. Despite the historical filename, it no longer creates transcripts.
- `azure_realtime.py` manages the stateful Azure Realtime WebSocket, VAD lifecycle, forced answer-update function calls, interruption, retry, and reconnect behavior.
- `chat.py` handles only explicit manual-analysis requests.
- `overlay.py` maintains the combined visible answer and manual action UI. There is no live transcript panel or microphone transcription path.

The Realtime model must call:

```json
{
  "name": "update_visible_answer",
  "arguments": {
    "action": "append | reset | no_update",
    "text": "only the new text required by that action"
  }
}
```

Function arguments are applied only after the call is complete. Cancelled, malformed, and stale responses never partially update the overlay.

## Setup

1. Create and activate a virtual environment:

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Create the environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Configure the manual-analysis resource and these strict Realtime variables:

   ```env
   AZURE_OPENAI_REALTIME_API_KEY=...
   AZURE_OPENAI_REALTIME_ENDPOINT=https://your-resource.openai.azure.com
   AZURE_OPENAI_REALTIME_DEPLOYMENT=gpt-realtime-2.1-mini
   ```

See `ENV_SETUP.md` for all settings.

## Usage

```powershell
python ai_live.py
```

Desktop audio streams continuously, but the model creates answers only while Auto-Answer is enabled.

- **Auto-Answer**: enable or disable automatic Realtime answer requests.
- **Text Input**: submit a typed question, optionally with screenshots.
- **Screenshot**: queue a screenshot for the next manual request.
- **Resume**: upload, replace, or remove resume context.
- **Code Analysis** and **General Analysis**: run explicit manual-analysis requests.
- **Clear Context**: clear the visible answers, manual history, and restart the Realtime conversation.

## Verification

```powershell
python -m unittest discover -s tests -v
```

## License

[MIT License](LICENSE)
