# AI-Live

AI-Live is a Windows desktop overlay for live transcription and manual AI analysis. It listens to your microphone and desktop audio, shows transcripts in a side panel, and lets you explicitly trigger analysis with buttons such as Text Input, Code Analysis, and General Analysis.

## Features

- Live microphone transcription with Azure OpenAI realtime audio and `whisper-1` transcription
- Live desktop/loopback transcription with optional suggested interviewer answers from Azure OpenAI `gpt-5.4-nano`
- Manual screenshot capture and automatic screenshot capture for analysis requests
- Resume PDF upload with local MarkItDown cache for personalized auto and general answers
- Manual analysis buttons for coding, general, and follow-up questions using Azure OpenAI `gpt-5.5`
- Single latest-answer display with rendered Markdown and syntax-highlighted code
- Transparent, draggable PyQt6 overlay that can be excluded from screen capture on Windows

## Architecture

- `ai_live.py` starts the PyQt overlay, live transcription manager, and manual analysis handlers.
- `live_transcription.py` captures mic and desktop audio and feeds raw PCM chunks to Azure realtime transcription.
- `azure_realtime.py` manages Azure realtime WebSocket transcription sessions and callbacks.
- `chat.py` handles Azure Responses API analysis requests and auto-answer generation.
- `overlay.py` contains the UI, transcript panel, screenshot queue, and manual action buttons.

## Setup

1. Create and activate a virtual environment:

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

2. Install runtime dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Create your environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Edit `.env` and set the purpose-specific Azure keys/endpoints for analysis, auto-answer, and transcription. If your Azure deployment names differ from the defaults, set the deployment override variables shown in `.env.example`.

## Usage

Run the app:

```powershell
python ai_live.py
```

The app does not automatically answer spoken queries unless Auto-Answer is enabled. Use the transcript panel and action buttons to decide when analysis should run:

- **Text Input**: ask a typed question, optionally with screenshots enabled.
- **Screenshot**: queue a screenshot for the next manual analysis request.
- **Resume**: choose a resume PDF from the file picker. The app converts it to Markdown, caches that converted context locally, and uses it for Auto-Answer and General Analysis when the question calls for personal experience, projects, skills, or examples. Click Resume again to replace or remove the cached resume context.
- **Code Analysis**: analyze the latest selected or recent transcripts plus screenshot context as a coding problem.
- **General Analysis**: answer the latest selected or recent transcripts as a non-coding interview question.
- **Auto-Answer**: when enabled, displays suggested answers generated from completed desktop transcription turns.

## Build Notes

Runtime dependencies are in `requirements.txt`. Build-only tools such as Nuitka are in `requirements-dev.txt`.

Generated build outputs, local executables, command launchers, crash reports, virtual environments, and `.env` are ignored. If a local build/debug artifact ever contains API keys, delete it and rotate those keys.

## License

[MIT License](LICENSE)
