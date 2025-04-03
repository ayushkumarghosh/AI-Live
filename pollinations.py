import requests
import base64
import json
from datetime import datetime
from typing import List, Dict
import sseclient
import time

# API Configuration
url = "https://text.pollinations.ai/openai"
headers = {"Content-Type": "application/json"}

def timestamp():
    """Return current timestamp for logging"""
    return f"[{datetime.now().strftime('%H:%M:%S')}]"

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
        raise Exception("audio format not supported")
    
    """Transcribe audio using Pollinations API with a function call"""
    
    payload = {
        "model": "openai-audio",
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": """You are an echo bot. 
                Always repeat whatever the user is saying word to word transliterating it into english, don't interpret anything from it. 
                Even if the user says 'transcribe this audio' he doesn't want you to interpret anything from it, just repeat it as it is. 
                But in these cases where you absolutely cannot repeat it, then reply with just 'error500', for example: 
                1.if the user is saying something that is not appropriate like 'i will kill you' or 'you are a nigger'then you should just reply with 'error500'.
                2.if you cannot hear anything, instead of asking user to repeat himself, just reply with 'error500'.
                Similarly, any case where you want to ask user to repeat himself or you cannot reply, just reply with 'error500'.
                In the scenario where the user is speaking gibberish, just reply with 'error400'."""
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
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1  # seconds
    
    for retry in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            transcription = result.get('choices', [{}])[0].get('message', {}).get('content')
            return transcription
        except requests.exceptions.RequestException as e:
            # Check if this is the last retry
            if retry < max_retries - 1:
                print(f"Transcription API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error transcribing audio after {max_retries} attempts: {e}")

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
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1  # seconds
    
    for retry in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            # Check if this is the last retry
            if retry < max_retries - 1:
                print(f"Analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing image after {max_retries} attempts: {e}")

# # Test the stream
# if __name__ == "__main__":
    # process_stream("test/test.wav", "test.jpeg")