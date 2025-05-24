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

# Google Gemini API setup
gemini_api_key = os.getenv("GEMINI_API")
genai.configure(api_key=gemini_api_key)

model = genai.GenerativeModel('gemini-2.5-flash-preview-04-17')
pro_model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25')

# Custom analyze prompt
analyze_prompt = "Analyze the desktop audio (if any) along with the screenshots and provide a helpful response. If the screenshot or desktop audio contains a coding problem, provide a complete working solution as follows: For a new/first-time question, first briefly explain both the naive approach and the optimized approach (without code), THEN implement both approaches with complete code. For follow-up questions or improvements to an existing solution, briefly explain the improvement first, then only focus on implementing the improved optimized solution - don't repeat the naive approach again. If the screenshot shows a LeetCode-like interface or any code cell with an existing code snippet, always use both the programming language shown and the code snippet itself as your starting point: directly modify, extend, or complete that code rather than starting from scratch or ignoring it. Ensure any code is ready to submit with no missing parts. For non-coding content, provide a detailed analysis relevant to what's shown in the screenshot. If you don't have a clear answer for either coding or non-coding problems, fabricate a reasonable and relevant answer instead. Never respond that you don't know or can't answer - always provide some answer. Always be thorough and complete in your response."

# Super analyze prompt focused on optimized coding solutions
super_analyze_prompt = "Analyze the screenshot and desktop audio (if any) and focus on solving any coding problem shown. If the screenshot shows a LeetCode-like interface or any code with an existing code snippet, always use both the programming language shown and the code snippet itself as your starting point: directly modify, extend, or complete that code rather than starting from scratch or ignoring it. Follow these steps: (1) If there's code in the screenshot, understand what it's trying to do and its context, (2) Explain your optimized approach as if explaining to an interviewer - clearly articulate the time and space complexity, trade-offs, and logic behind your solution, (3) Implement the complete optimized solution with proper edge case handling and clean, well-commented code. For non-coding content, provide a detailed expert-level analysis of what's shown. Always be thorough and provide production-ready solutions."

generation_config={
    "temperature": 0.6,
    # "top_p": 0.1,
    # "top_k": 100,
    "max_output_tokens": 50000,
    "response_mime_type": "application/json",
    "response_schema": {
        "type": "object",
        "properties": {
            "user_query": {"type": "string", "description": "The user's current query (the text input)"},
            "response": {"type": "string", "description": "Your response to the user's query. If the user asks you to do something, do it immediately. If the user asks a question, answer it to the best of your ability. Use the desktop audio and screen image to help you answer the user's query but only if it is relevant to the user's query."}
        },
        "required": ["user_query", "response"]
    },
}

def timestamp():
    """Return current timestamp for logging"""
    return f"[{datetime.now().strftime('%H:%M:%S')}]"

# Initialize a global chat session
chat = model.start_chat(history=[])
pro_chat = pro_model.start_chat(history=[])

def clear_chat_history():
    """Clear the chat history for both models and start fresh sessions"""
    global chat, pro_chat
    
    # Create new chat sessions for both models
    chat = model.start_chat(history=[])
    pro_chat = pro_model.start_chat(history=[])
    
    print(f"{timestamp()} Chat history cleared for both models")
    return True

def analyze_with_audio_and_image(audio_base64: str, audio_format: str, 
                                images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze audio and image using Google Gemini's chat history"""
    global chat
    
    # Add current content
    current_parts = []
    
    # Add explanatory text for microphone audio
    current_parts.append({"text": "This is the user's query, always prioritize it and answer it as you are helping the user when they are in an interview(for a software engineering role) or coding session. If necessary fabricate an answer if you don't know the answer:"})
    
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
            
            current_parts.append({"text": "This is the desktop audio output from the user's system. You MUST provide a comprehensive answer to ANY question or problem it contains. If it's a coding problem, provide a complete solution with both explanation and implementation. If it's any other type of question or problem, provide a detailed answer with examples if applicable. If you don't know the answer, ALWAYS fabricate a reasonable, detailed answer rather than saying you don't know. Never respond that you can't answer - provide a confident, complete response regardless of the question type:" + analyze_prompt})
            
            desktop_audio_part = {
                "inline_data": {
                    "mime_type": f"audio/{audio_format}",
                    "data": desktop_audio_base64
                }
            }
            current_parts.append(desktop_audio_part)
        except Exception as e:
            print(f"Warning: Invalid current desktop audio data: {e}")
    
    # Add explanatory text for the screens
    if images_base64:
        current_parts.append({"text": "These are the screens of the user. Analyze them thoroughly and provide a comprehensive answer to any problem or question shown. If they contain a coding problem, solve it completely with both explanation and code implementation. For any other type of content, provide a detailed analysis or answer. If you don't know, always fabricate a reasonable, confident answer:"})
        # Add each image as a separate part
        for image_base64 in images_base64:
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
            # Using Gemini's chat history functionality
            response = chat.send_message(
                current_parts,
                generation_config=generation_config
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

def analyze_with_text_input(text_input: str, 
                          images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze text input and image using Google Gemini's chat history"""
    global chat
    
    # Add current content
    current_parts = []
    
    # Add explanatory text for the user's text input
    current_parts.append({"text": f"This is the user's query (typed text), always prioritize it: {text_input}"})
    
    # Add desktop audio if available
    if desktop_audio_base64:
        current_parts.append({"text": "This is the desktop audio output from the user's system. You MUST provide a comprehensive answer to ANY question or problem it contains. If it's a coding problem, provide a complete solution with both explanation and implementation. If it's any other type of question or problem, provide a detailed answer with examples if applicable. If you don't know the answer, ALWAYS fabricate a reasonable, detailed answer rather than saying you don't know. Never respond that you can't answer - provide a confident, complete response regardless of the question type:" + analyze_prompt})
        
        desktop_audio_part = {
            "inline_data": {
                "mime_type": "audio/wav",
                "data": desktop_audio_base64
            }
        }
        current_parts.append(desktop_audio_part)
    
    # Add explanatory text for the screens
    if images_base64:
        current_parts.append({"text": "These are the screens of the user. Analyze them thoroughly and provide a comprehensive answer to any problem or question shown. If they contain a coding problem, solve it completely with both explanation and code implementation. For any other type of content, provide a detailed analysis or answer. If you don't know, always fabricate a reasonable, confident answer:"})
        # Add each image as a separate part
        for image_base64 in images_base64:
            img_part = {
                "inline_data": {
                    "mime_type": f"image/{image_format}",
                    "data": image_base64
                }
            }
            current_parts.append(img_part)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Using Gemini's chat history functionality
            response = chat.send_message(
                current_parts,
                generation_config=generation_config
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

def analyze_with_pro_model(text_input: str, 
                          images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze text input and image using Gemini Pro model for advanced coding analysis"""
    global pro_chat
    
    # Add current content
    current_parts = []
    
    # Add explanatory text for the user's text input
    current_parts.append({"text": f"This is the user's query (typed text), always prioritize it: {text_input}"})
    
    # Add desktop audio if available
    if desktop_audio_base64:
        current_parts.append({"text": "This is the desktop audio output from the user's system. You MUST provide a comprehensive answer to ANY question or problem it contains. If it's a coding problem, provide a complete solution with both explanation and implementation. If it's any other type of question or problem, provide a detailed answer with examples if applicable. If you don't know the answer, ALWAYS fabricate a reasonable, detailed answer rather than saying you don't know. Never respond that you can't answer - provide a confident, complete response regardless of the question type:" + super_analyze_prompt})
        
        desktop_audio_part = {
            "inline_data": {
                "mime_type": "audio/wav",
                "data": desktop_audio_base64
            }
        }
        current_parts.append(desktop_audio_part)
    
    # Add explanatory text for the screens
    if images_base64:
        current_parts.append({"text": "These are the screens of the user. Analyze them thoroughly and provide a comprehensive answer to any problem or question shown. If they contain a coding problem, solve it completely with both explanation and code implementation. For any other type of content, provide a detailed analysis or answer. If you don't know, always fabricate a reasonable, confident answer:"})
        # Add each image as a separate part
        for image_base64 in images_base64:
            img_part = {
                "inline_data": {
                    "mime_type": f"image/{image_format}",
                    "data": image_base64
                }
            }
            current_parts.append(img_part)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Using Gemini Pro model chat history functionality
            response = pro_chat.send_message(
                current_parts,
                generation_config={
                    "max_output_tokens": 65536
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
                print("Warning: Pro model response was not valid JSON. Returning raw response.")
                return {"user_query": text_input, "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Pro analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing with Pro model after {max_retries} attempts: {e}")

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
