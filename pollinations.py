import requests
import base64
import json
from datetime import datetime
from typing import List, Dict
import sseclient

# API Configuration
url = "https://text.pollinations.ai/openai"
headers = {"Content-Type": "application/json"}

class ChatHistory:
    def __init__(self):
        self.history: List[Dict] = []

    def add_entry(self, transcript: str, response: dict, image_base64: str):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "transcript": transcript,
            "response": response.get('choices', [{}])[0].get('message', {}).get('content') if response else None,
            "image_base64": image_base64
        }
        self.history.append(entry)

    def get_context(self, lookback: int = 3) -> List[Dict]:
        """Get the last n entries for context"""
        return self.history[-lookback:] if len(self.history) > lookback else self.history

def encode_audio_base64(file_path: str) -> str:
    """Convert audio file to base64"""
    with open(file_path, "rb") as audio_file:
        return base64.b64encode(audio_file.read()).decode('utf-8')

def encode_image_base64(file_path: str) -> str:
    """Convert image file to base64"""
    with open(file_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def transcribe(audio_base64: str, audio_format: str) -> str:
    supported_formats = ['mp3', 'mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm'] 
    if audio_format not in supported_formats:
        print(f"Warning: Potentially unsupported audio format '{audio_format}'. Check API documentation.")
        raise Exception("audio format not supported")
    
    """Transcribe audio using Pollinations API with a function call"""
    payload = {
        "model": "openai-audio",
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": "You are an echo bot. Always repeat whatever the user is saying word to word, don't interpret anything from it, even if the user says 'transcribe this audio' he doesn't want you to interpret anything from it, just repeat it as it is."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_base64,
                            "format": audio_format
                        }
                    }
                ]
            }
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        transcription = result.get('choices', [{}])[0].get('message', {}).get('content')
        return transcription
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error transcribing audio: {e}")

def analyze_image_with_history(chat_history: ChatHistory, base64_image: str, image_format: str, transcript: str):
    """Analyze image and transcript with chat history context"""
    context = chat_history.get_context()
    
    # Build messages with history
    messages = []
    for entry in context:
        msg_content = [
            {"type": "text", "text": f"Previous transcript: {entry['transcript']}"},
            {"type": "text", "text": f"Previous response: {entry['response']}"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{entry['image_base64']}"}
            }
        ]
        messages.append({"role": "user", "content": msg_content})

    # Add current message (image is always present as per your requirement)
    current_content = [
        {"type": "text", "text": transcript},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/{image_format};base64,{base64_image}"}
        }
    ]
    messages.append({"role": "user", "content": current_content})

    payload = {
        "model": "openai-large", 
        "messages": messages,
        "max_tokens": 16000,
        "stream": True
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error analyzing image: {e}")

# Usage Example
def process_stream(audio_file: str, image_file: str):
    chat = ChatHistory()
    
    # Encode inputs
    audio_base64 = encode_audio_base64(audio_file)
    image_base64 = encode_image_base64(image_file)

    # Transcribe audio
    transcript = transcribe(audio_base64, "wav")
    if not transcript:
        print("Transcript generation failed.")
        return
    print("Transcript: " + transcript)

    # Analyze with history
    response = analyze_image_with_history(chat, image_base64, "jpeg", transcript)

    client = sseclient.SSEClient(response)
    full_response = ""
    print("Streaming response:")
    for event in client.events():
        if event.data:
            try:
                # Handle potential '[DONE]' marker
                if event.data.strip() == '[DONE]':
                    print("\nStream finished.")
                    break
                chunk = json.loads(event.data)
                content = None
                if len(chunk.get('choices', [{}])) > 0:
                    content = chunk.get('choices', [{}])[0].get('delta', {}).get('content')
                if content:
                    print(content, end='', flush=True)
                    full_response += content
            except json.JSONDecodeError:
                    print(f"\nReceived non-JSON data (or marker other than [DONE]): {event.data}")

    print("\n--- End of Stream ---")

# # Test the stream
if __name__ == "__main__":
    process_stream("test/test.wav", "test.jpeg")