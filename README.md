# AI-Live

An intelligent voice-activated assistant that responds to spoken queries while analyzing your screen content in real-time.

## Overview

AI-Live is a powerful multimodal system that combines:
- **Voice Recognition**: Captures and transcribes your speech
- **Screen Analysis**: Takes screenshots to understand your visual context
- **Context-Aware Responses**: Maintains conversation history for more relevant interactions

The system processes your spoken questions, captures your screen, and provides AI-powered responses that take into account both what you say and what you see.

## Features

- **Real-time Speech Processing**: Uses Silero VAD (Voice Activity Detection) for accurate speech detection
- **Screenshot Analysis**: Automatically captures and analyzes your screen when you speak
- **Streaming Responses**: Provides character-by-character streaming responses for a natural conversation feel
- **Conversation History**: Maintains context from previous interactions for more coherent dialogue

## Architecture

The system consists of three main components:

1. **Speech Capture** (`speech_capture.py`): Records and processes audio input using PyAudio and Silero VAD
2. **API Integration** (`pollinations.py`): Handles communication with the Pollinations AI API for transcription and analysis
3. **Main Application** (`ai_live.py`): Orchestrates the system using asyncio for concurrent processing

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/ayushkumarghosh/AI-Live.git
   cd AI-Live
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

Run the main application:
```
python ai_live.py
```

Speak naturally to the system and watch as it processes your speech, analyzes your screen, and responds accordingly.

## How It Works

1. The system continuously listens for speech using VAD to detect when you start and stop speaking
2. When speech is detected, the audio is captured and converted to a WAV format
3. The audio is transcribed using the Pollinations API
4. A screenshot is captured to provide visual context
5. Both the transcription and screenshot are sent to the API for analysis
6. The response is streamed back character by character for a natural conversation experience
7. The interaction is stored in the chat history for context in future exchanges

## License

[MIT License](LICENSE)

## Acknowledgements

- [Silero VAD](https://github.com/snakers4/silero-vad) for speech detection
- [Pollinations AI](https://pollinations.ai) for AI processing capabilities
