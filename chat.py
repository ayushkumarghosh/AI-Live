# from openai import AzureOpenAI
# from openai import OpenAI
import google.generativeai as genai
import base64
from datetime import datetime
from typing import List, Dict
import time
import os
import json

# Google Gemini API setup
gemini_api_key = os.getenv("GEMINI_API")
genai.configure(api_key=gemini_api_key)

def timestamp():
    """Return current timestamp for logging"""
    return f"[{datetime.now().strftime('%H:%M:%S')}]"

class ChatHistory:
    def __init__(self):
        self.history: List[Dict] = []

    def add_entry(self, audio_base64: str, response: str, image_base64: str):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "audio_base64": audio_base64,
            "response": response,
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

def analyze_with_audio_and_image(chat_history: ChatHistory, audio_base64: str, audio_format: str, image_base64: str, image_format: str):
    """Analyze audio and image with chat history context using Google Gemini"""
    context = chat_history.get_context(lookback=10)
    
    # Initialize Gemini model
    model = genai.GenerativeModel('gemini-2.0-flash-lite')
    
    # Create a chat session
    chat = model.start_chat(history=[])
    
    # Add system prompt for English transliteration
    system_prompt = "Your responses should always be in English. No need to transcribe anything, just transliterate your answer to English."
    chat.send_message({"text": f"System: {system_prompt}"})
    
    # Add history context
    for entry in context:
        # Create a parts list for multimodal content
        parts = []
        
        # Add text with previous response context
        parts.append({"text": f"Previous response: {entry['response']}"})
        
        # Add image content
        img_part = {
            "inline_data": {
                "mime_type": f"image/jpeg",
                "data": entry['image_base64']
            }
        }
        parts.append(img_part)
        
        # Add audio content
        audio_part = {
            "inline_data": {
                "mime_type": f"audio/{audio_format}",
                "data": entry['audio_base64']
            }
        }
        parts.append(audio_part)
        
        # Add this as a user message to the chat
        chat.send_message(parts)
    
    # Add current content
    current_parts = []
    
    # Add audio content - Gemini 2.0 Flash supports audio input directly
    audio_part = {
        "inline_data": {
            "mime_type": f"audio/{audio_format}",
            "data": audio_base64
        }
    }
    current_parts.append(audio_part)
    
    # Add image content
    current_parts.append({"text": "This is the screen of the user, analyze it only if it is relevant to the question:"})
    img_part = {
        "inline_data": {
            "mime_type": f"image/{image_format}",
            "data": image_base64
        }
    }
    current_parts.append(img_part)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1  # seconds
    
    for retry in range(max_retries):
        try:
            # Using Gemini's streaming response
            response = chat.send_message(current_parts, stream=True)
            return response
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing audio and image after {max_retries} attempts: {e}")

# Function to transcribe audio using Google's Speech-to-Text API
# def transcribe_audio(audio_base64: str, audio_format: str) -> str:
#     """
#     Transcribe audio using Google's Speech-to-Text API
#     """
#     # Decode the base64 audio
#     audio_content = base64.b64decode(audio_base64)
#     
#     # Configure the speech recognition request
#     audio = speech.RecognitionAudio(content=audio_content)
#     config = speech.RecognitionConfig(
#         encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
#         sample_rate_hertz=16000,  # Adjust based on your audio
#         language_code="en-US",
#     )
#     
#     # Make the API call
#     response = speech_client.recognize(config=config, audio=audio)
#     
#     # Extract and return the transcript
#     transcript = ""
#     for result in response.results:
#         transcript += result.alternatives[0].transcript
#     
#     return transcript

def process_stream_response(response):
    """Process a streaming response from Gemini"""
    full_response = ""
    for chunk in response:
        if chunk.text:
            content = chunk.text
            full_response += content
            print(content, end="", flush=True)
    print()  # Add a newline at the end
    return full_response

# Example usage
# if __name__ == "__main__":
#     # Initialize chat history
#     history = ChatHistory()
#     
#     # Example paths - replace with your actual files
#     audio_path = "test/test.wav"
#     image_path = "test/test.jpeg"
#     
#     # Encode files
#     audio_base64 = encode_audio_base64(audio_path)
#     image_base64 = encode_image_base64(image_path)
#     
#     # Get streaming response
#     stream_response = analyze_with_audio_and_image(history, audio_base64, "wav", image_base64, "jpeg")
#     
#     # Process the stream
#     full_response = process_stream_response(stream_response)
#     
#     # Add the interaction to history
#     history.add_entry(audio_base64, full_response, image_base64)
