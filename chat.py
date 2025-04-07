# from openai import AzureOpenAI
# from openai import OpenAI
import google.generativeai as genai
import base64
from datetime import datetime
from typing import List, Dict
import time
import os
import json
import io
import wave

# Import from speech_capture
from speech_capture import get_desktop_speech_segments, desktop_speech_segments, CHANNELS, RATE

# Google Gemini API setup
gemini_api_key = os.getenv("GEMINI_API")
genai.configure(api_key=gemini_api_key)

def timestamp():
    """Return current timestamp for logging"""
    return f"[{datetime.now().strftime('%H:%M:%S')}]"

class ChatHistory:
    def __init__(self):
        self.history: List[Dict] = []

    def add_entry(self, audio_base64: str, response: str, image_base64: str, desktop_audio_base64: str = ""):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "audio_base64": audio_base64,
            "desktop_audio_base64": desktop_audio_base64,
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

def analyze_with_audio_and_image(chat_history: ChatHistory, audio_base64: str, audio_format: str, 
                                image_base64: str, image_format: str, desktop_audio_base64: str = ""):
    """Analyze audio and image with chat history context using Google Gemini"""
    context = chat_history.get_context()
    
    # Initialize Gemini model
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    # Create a chat session
    chat = model.start_chat(history=[])
    
    # Add history context
    for entry in context:
        # Create a parts list for multimodal content
        parts = []
        
        # Add text with previous response context
        parts.append({"text": f"Previous response: {entry['response']}"})
        
        # Add explanatory text for the screen image
        parts.append({"text": "This was the screen of the user, analyze it only if it is relevant to the user's current query:"})
        
        # Add image content - as a separate part
        img_part = {
            "inline_data": {
                "mime_type": f"image/jpeg",
                "data": entry['image_base64']
            }
        }
        parts.append(img_part)
        
        # Add explanatory text for microphone audio
        parts.append({"text": "This was the user's query:"})
        
        # Add audio content - as a separate part
        if entry.get('audio_base64') and len(entry['audio_base64']) > 100:  # Only add valid audio
            try:
                # Validate base64 data
                base64.b64decode(entry['audio_base64'])
                
                audio_part = {
                    "inline_data": {
                        "mime_type": f"audio/{audio_format}",
                        "data": entry['audio_base64']
                    }
                }
                parts.append(audio_part)
            except Exception as e:
                print(f"Warning: Invalid audio data in history: {e}")
                parts.append({"text": "Audio data was not available or valid."})
        else:
            parts.append({"text": "Audio data was not available."})
        
        # Add desktop audio if available
        if entry.get('desktop_audio_base64') and len(entry.get('desktop_audio_base64', '')) > 100:
            try:
                # Validate base64 data
                base64.b64decode(entry['desktop_audio_base64'])
                
                # Add explanatory text
                parts.append({"text": "This was the desktop audio output from the user's system, analyze it only if it is relevant to the query:"})
                
                desktop_audio_part = {
                    "inline_data": {
                        "mime_type": f"audio/{audio_format}",
                        "data": entry['desktop_audio_base64']
                    }
                }
                parts.append(desktop_audio_part)
            except Exception as e:
                print(f"Warning: Invalid desktop audio data in history: {e}")
        
        # Add this as a user message to the chat
        chat.send_message(parts)
    
    # Add current content
    current_parts = []
    
    # Add explanatory text for microphone audio
    current_parts.append({"text": "This is the user's current query, always prioritize it:"})
    
    # Add audio content as a separate part if valid
    if audio_base64 and len(audio_base64) > 100:  # Ensure valid audio data
        try:
            # Validate base64 data
            base64.b64decode(audio_base64)
            
            audio_part = {
                "inline_data": {
                    "mime_type": f"audio/{audio_format}",
                    "data": audio_base64
                }
            }
            current_parts.append(audio_part)
        except Exception as e:
            print(f"Warning: Invalid current audio data: {e}")
            current_parts.append({"text": "Audio data was not available or valid. Please infer the query from context."})
    else:
        current_parts.append({"text": "Audio data was not available. Please infer the query from context."})
    
    # Add desktop audio if available and valid
    if desktop_audio_base64 and len(desktop_audio_base64) > 100:
        try:
            # Validate base64 data
            base64.b64decode(desktop_audio_base64)
            
            current_parts.append({"text": "This is the current desktop audio output from the user's system, analyze it only if it is relevant to the query:"})
            
            desktop_audio_part = {
                "inline_data": {
                    "mime_type": f"audio/{audio_format}",
                    "data": desktop_audio_base64
                }
            }
            current_parts.append(desktop_audio_part)
        except Exception as e:
            print(f"Warning: Invalid current desktop audio data: {e}")
    
    # Add explanatory text for the screen
    current_parts.append({"text": "This is the current screen of the user, analyze it only if it is relevant to the query:"})
    
    # Add image content as a separate part
    img_part = {
        "inline_data": {
            "mime_type": f"image/{image_format}",
            "data": image_base64
        }
    }
    current_parts.append(img_part)
    
    # Add instruction for the model
    current_parts.append({
        "text": "First extract the user's query and then generate a helpful response to the user's query."
    })
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1  # seconds
    
    for retry in range(max_retries):
        try:
            # Using Gemini's generate_content with structured output schema
            response = model.generate_content(
                current_parts,
                generation_config={
                    "temperature": 0,
                    "max_output_tokens": 6000,
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "object",
                        "properties": {
                            "user_query": {"type": "string", "description": "The user's query(transliterated to english if needed)"},
                            "response": {"type": "string", "description": "The AI's response(transliterated to english if needed) to the user's query"}
                        },
                        "required": ["user_query", "response"]
                    },
                }
            )
            
            # Extract and parse the response text
            response_text = response.text
            
            try:
                # Parse the JSON response
                response_json = json.loads(response_text)
                return response_json
            except json.JSONDecodeError:
                # If JSON parsing fails, return a fallback structure
                print("Warning: Response was not valid JSON. Returning raw response.")
                return {"user_query": "Could not extract query", "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing audio and image after {max_retries} attempts: {e}")

def analyze_with_text_input(chat_history: ChatHistory, text_input: str, 
                          image_base64: str, image_format: str, desktop_audio_base64: str = ""):
    """Analyze text input and image with chat history context using Google Gemini"""
    context = chat_history.get_context()
    
    # Initialize Gemini model
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    # Create a chat session
    chat = model.start_chat(history=[])
    
    # Add history context
    for entry in context:
        # Create a parts list for multimodal content
        parts = []
        
        # Add text with previous response context
        parts.append({"text": f"Previous response: {entry['response']}"})
        
        # Add explanatory text for the screen image
        parts.append({"text": "This was the screen of the user, analyze it only if it is relevant to the user's current query:"})
        
        # Add image content - as a separate part
        img_part = {
            "inline_data": {
                "mime_type": f"image/jpeg",
                "data": entry['image_base64']
            }
        }
        parts.append(img_part)
        
        # Add explanatory text for previous user query
        parts.append({"text": "This was the user's query:"})
        
        # Add previous audio if available (for context)
        if entry.get('audio_base64'):
            audio_part = {
                "inline_data": {
                    "mime_type": "audio/wav",
                    "data": entry['audio_base64']
                }
            }
            parts.append(audio_part)
        
        # Add desktop audio if available
        if entry.get('desktop_audio_base64'):
            # Add explanatory text
            parts.append({"text": "This was the desktop audio output from the user's system, analyze it only if it is relevant to the query:"})
            
            desktop_audio_part = {
                "inline_data": {
                    "mime_type": "audio/wav",
                    "data": entry['desktop_audio_base64']
                }
            }
            parts.append(desktop_audio_part)
        
        # Add this as a user message to the chat
        chat.send_message(parts)
    
    # Add current content
    current_parts = []
    
    # Add explanatory text for the user's text input
    current_parts.append({"text": f"This is the user's current query (typed text), always prioritize it: {text_input}"})
    
    # Add desktop audio if available
    if desktop_audio_base64:
        current_parts.append({"text": "This is the current desktop audio output from the user's system, analyze it only if it is relevant to the query:"})
        
        desktop_audio_part = {
            "inline_data": {
                "mime_type": "audio/wav",
                "data": desktop_audio_base64
            }
        }
        current_parts.append(desktop_audio_part)
    
    # Add explanatory text for the screen
    current_parts.append({"text": "This is the current screen of the user, analyze it only if it is relevant to the query:"})
    
    # Add image content as a separate part
    img_part = {
        "inline_data": {
            "mime_type": f"image/{image_format}",
            "data": image_base64
        }
    }
    current_parts.append(img_part)
    
    # Add instruction for the model
    current_parts.append({
        "text": "Generate a helpful response to the user's text query."
    })
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1  # seconds
    
    for retry in range(max_retries):
        try:
            # Using Gemini's generate_content with structured output schema
            response = model.generate_content(
                current_parts,
                generation_config={
                    "temperature": 0,
                    "max_output_tokens": 6000,
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "object",
                        "properties": {
                            "user_query": {"type": "string", "description": "The user's query (the text input)"},
                            "response": {"type": "string", "description": "The AI's response to the user's query"}
                        },
                        "required": ["user_query", "response"]
                    },
                }
            )
            
            # Extract and parse the response text
            response_text = response.text
            
            try:
                # Parse the JSON response
                response_json = json.loads(response_text)
                return response_json
            except json.JSONDecodeError:
                # If JSON parsing fails, return a fallback structure
                print("Warning: Response was not valid JSON. Returning raw response.")
                return {"user_query": text_input, "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing text input and image after {max_retries} attempts: {e}")

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

# def process_stream_response(response):
#     """Process a streaming response from Gemini"""
#     full_response = ""
#     for chunk in response:
#         if chunk.text:
#             content = chunk.text
#             full_response += content
#             print(content, end="", flush=True)
#     print()  # Add a newline at the end
    
#     try:
#         # Parse the JSON response
#         response_json = json.loads(full_response)
#         return response_json
#     except json.JSONDecodeError:
#         # If JSON parsing fails, return the raw response
#         print("Warning: Response was not valid JSON. Returning raw response.")
#         return {"user_query": "Could not extract query", "response": full_response}

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
#     # Get response
#     response_json = analyze_with_audio_and_image(history, audio_base64, "wav", image_base64, "jpeg")
#     
#     # Add the interaction to history
#     history.add_entry(audio_base64, response_json.get("response", ""), image_base64)
