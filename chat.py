# from openai import AzureOpenAI
# from openai import OpenAI
from google import genai
from google.genai import types
import base64
from datetime import datetime
from typing import List, Dict
import time
import os
import json
import io
import wave
import requests

# Google Gemini API setup
gemini_api_key = os.getenv("GEMINI_API")

# OpenRouter API setup for DeepSeek
openrouter_api_key = os.getenv("DEEPSEEK")

# Initialize the new GenAI client
client = genai.Client(api_key=gemini_api_key)

# Model names
GEMINI_FLASH_MODEL = "gemini-2.5-flash-preview-05-20"
DEEPSEEK_MODEL = "tngtech/deepseek-r1t-chimera:free"

# Chat instances for maintaining conversation history
chat_flash = None
deepseek_chat_history = []  # Separate chat history for DeepSeek

def initialize_chat_instances():
    """Initialize chat instances for Gemini models"""
    global chat_flash
    chat_flash = client.chats.create(model=GEMINI_FLASH_MODEL)

def reset_chat_history():
    """Reset chat history by creating new chat instances"""
    global chat_flash, deepseek_chat_history
    chat_flash = client.chats.create(model=GEMINI_FLASH_MODEL)
    deepseek_chat_history = []
    print(f"{timestamp()} Chat history reset for all models")

# Separated prompts for different functionalities

# 1. Code problem analysis prompt (regular model)
code_problem_prompt = "Read the transcriptions (if any) along with the screenshots to solve coding problems. If the screenshot or transcriptions contains a coding problem, provide a complete working solution as follows: For a new/first-time question, first briefly explain both the naive approach and the optimized approach (without code), THEN implement both approaches with complete code optimizing for time complexity as much as possible. If the screenshot shows a LeetCode-like interface or any code cell with an existing code snippet, always use both the programming language shown and the code snippet itself as your starting point without changing the signature of the function: directly modify, extend, or complete that code rather than starting from scratch or ignoring it. Ensure any code is ready to submit with no missing parts. Always be thorough and complete in your response."

# 2. Non-coding problem analysis prompt (regular model)
general_analysis_prompt = "Read the transcriptions along with the screenshots and answer any questions being asked. Respond as if you are the candidate being interviewed for a software engineering role. Give thorough, professional answers that showcase relevant skills and experience. Be concise but thorough, and maintain a professional tone throughout. Disregard any other sounds from the desktop audio only consider the speech. ALWAYS ANSWER FIRST WITHOUT EXPLAINING YOUR ANSWER THEN EXPLAIN YOUR ANSWER. If you don't know the answer, fabricate a relevant and reasonable answer instead. Never respond that you don't know or can't answer—always provide some answer."


# 3. Repeat analysis prompt (regular model) 
repeat_analysis_prompt = "Read the transcriptions (if any) along with the screenshots for errors. Briefly explain the improvement first, then focus on implementing the improved optimized solution - don't repeat the naive approach again. If this is a coding problem, provide the enhanced solution with proper explanation. For non-coding content, provide updated or refined analysis based on the new context. Always be thorough and complete in your response."

# 4. Code problem analysis prompt (pro model)
code_problem_pro_prompt = "Read the screenshot and transcriptions (if any) and focus on solving any coding problem shown optimizing for time complexity as much as possible. If the screenshot shows a LeetCode-like interface or any code with an existing code snippet, always use both the programming language shown and the code snippet itself as your starting point without changing the signature of the function: directly modify, extend, or complete that code rather than starting from scratch or ignoring it. Follow these steps: (1) If there's code in the screenshot, understand what it's trying to do and its context, (2) Explain your optimized approach as if explaining to an interviewer - clearly articulate the time and space complexity, trade-offs, and logic behind your solution, (3) Implement the complete optimized solution (for time complexity) with proper edge case handling and clean, well-commented code. Always be thorough and complete solutions."

# 5. Repeat analysis prompt (pro model)
repeat_analysis_pro_prompt = "Read the screenshot and transcriptions (if any) for follow-up questions or improvements to coding problems using the Pro model. Focus if there's any error in the screenshot or transcriptions and implementing enhanced, optimized solutions with advanced algorithms and techniques. Explain the improvements, time and space complexity optimizations, and provide production-ready code with comprehensive error handling. Always be thorough and provide expert-level solutions."

# Legacy prompts (kept for backwards compatibility)
analyze_prompt = code_problem_prompt  # Default to code problem analysis
super_analyze_prompt = code_problem_pro_prompt  # Default to pro code analysis

# Initialize chat instances
initialize_chat_instances()

# Chat history to maintain context across multiple requests
chat_history = []

def prepare_image_parts(images_base64: List[str], image_format: str) -> List[types.Part]:
    """Convert base64 images to GenAI Part objects"""
    image_parts = []
    
    # Normalize image format to proper MIME type
    if image_format.lower() == 'jpg':
        mime_format = 'jpeg'
    else:
        mime_format = image_format.lower()
    
    for image_base64 in images_base64:
        try:
            # Decode base64 to bytes
            image_bytes = base64.b64decode(image_base64)
            
            # Create Part object using the new format
            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type=f'image/{mime_format}'
            )
            image_parts.append(image_part)
        except Exception as e:
            print(f"Warning: Failed to process image: {e}")
            continue
    
    return image_parts

def prepare_audio_parts(audio_base64: str, audio_format: str, audio_type: str = "user") -> List[types.Part]:
    """Convert base64 audio to GenAI Part objects"""
    audio_parts = []
    
    if audio_base64 and len(audio_base64) > 100:
        try:
            # Validate and decode base64 data
            audio_bytes = base64.b64decode(audio_base64)
            
            # Create Part object for audio
            audio_part = types.Part.from_bytes(
                data=audio_bytes,            mime_type=f'audio/{audio_format}'
            )
            audio_parts.append(audio_part)
        except Exception as e:
            print(f"Warning: Failed to process {audio_type} audio: {e}")
    
    return audio_parts

def timestamp():
    """Return current timestamp for logging"""
    return f"[{datetime.now().strftime('%H:%M:%S')}]"

# Transcription functions for DeepSeek integration

def transcribe_images_to_text(images_base64: List[str], image_format: str) -> str:
    """Transcribe images to text using Gemini 2.0 Flash for DeepSeek integration"""
    if not images_base64:
        return ""
    
    # Prepare content parts
    content_parts = []
    content_parts.append("Please provide a detailed description of what you see in these screenshots. Focus on any text, code, UI elements, error messages, or other relevant content. Be thorough and include all important details that would help someone understand what's happening on the screen.")
    
    # Add images
    image_parts = prepare_image_parts(images_base64, image_format)
    content_parts.extend(image_parts)
    
    max_retries = 3
    for retry in range(max_retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=8000
                )
            )
            return response.text
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Image transcription failed (attempt {retry+1}/{max_retries}): {e}. Retrying...")
                time.sleep(1)
            else:
                print(f"Failed to transcribe images after {max_retries} attempts: {e}")
                return "Failed to transcribe image content."

def transcribe_audio_to_text(audio_base64: str, audio_format: str, audio_type: str = "desktop") -> str:
    """Transcribe audio to text using Gemini 2.0 Flash for DeepSeek integration"""
    if not audio_base64 or len(audio_base64) <= 100:
        return ""
    
    # Prepare content parts
    content_parts = []
    content_parts.append(f"Please transcribe the following {audio_type} audio and provide the exact text/speech content. If there are any questions, problems, or instructions being discussed, make sure to capture them accurately.")
    
    # Add audio
    audio_parts = prepare_audio_parts(audio_base64, audio_format, audio_type)
    content_parts.extend(audio_parts)
    
    max_retries = 3
    for retry in range(max_retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=4000
                )
            )
            return response.text
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Audio transcription failed (attempt {retry+1}/{max_retries}): {e}. Retrying...")
                time.sleep(1)
            else:
                print(f"Failed to transcribe {audio_type} audio after {max_retries} attempts: {e}")
                return f"Failed to transcribe {audio_type} audio content."

def call_deepseek_api(messages: List[Dict], max_tokens: int = 50000) -> str:
    """Call DeepSeek API via OpenRouter"""
    if not openrouter_api_key:
        raise Exception("OPENROUTER_API_KEY environment variable is not set")
    
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    
    max_retries = 3
    for retry in range(max_retries):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=60
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            if retry < max_retries - 1:
                print(f"DeepSeek API call failed (attempt {retry+1}/{max_retries}): {e}. Retrying...")
                time.sleep(5)
            else:
                raise Exception(f"DeepSeek API call failed after {max_retries} attempts: {e}")

def clear_chat_history():
    """Clear the chat history and start fresh"""
    global chat_history, deepseek_chat_history
    chat_history = []
    deepseek_chat_history = []
    reset_chat_history()  # Also reset chat instances
    print(f"{timestamp()} Chat history cleared for all models")
    return True

def analyze_with_audio_and_image(audio_base64: str, audio_format: str, 
                                images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze audio and image using Google Gemini's new API format"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add explanatory text for microphone audio
    content_parts.append("This is the user's query, always prioritize it and answer it as you are helping the user when they are in an interview(for a software engineering role) or coding session. If necessary fabricate an answer if you don't know the answer:")
    
    # Add user audio if available
    user_audio_parts = prepare_audio_parts(audio_base64, audio_format, "user")
    if user_audio_parts:
        content_parts.extend(user_audio_parts)
    else:
        content_parts.append("Audio data was not available. Please infer the query from context.")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. You MUST provide a comprehensive answer to ANY question or problem it contains. If it's a coding problem, provide a complete solution with both explanation and implementation. If it's any other type of question or problem, provide a detailed answer with examples if applicable. If you don't know the answer, ALWAYS fabricate a reasonable, detailed answer rather than saying you don't know. Never respond that you can't answer - provide a confident, complete response regardless of the question type:" + analyze_prompt)
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, audio_format, "desktop")
        content_parts.extend(desktop_audio_parts)
    
    # Add images if available
    if images_base64:
        content_parts.append("These are the screens of the user. Analyze them thoroughly and provide a comprehensive answer to any problem or question shown. If they contain a coding problem, solve it completely with both explanation and code implementation. For any other type of content, provide a detailed analysis or answer. If you don't know, always fabricate a reasonable, confident answer:")
        
        image_parts = prepare_image_parts(images_base64, image_format)
        content_parts.extend(image_parts)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Generate content using the new API format
            response = client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=60000,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "user_query": {"type": "string", "description": "The user's current query (the text input)"},
                            "response": {"type": "string", "description": "Your response to the user's query. If the user asks you to do something, do it immediately. If the user asks a question, answer it to the best of your ability. Use the desktop audio and screen image to help you answer the user's query but only if it is relevant to the user's query."}
                        },
                        "required": ["user_query", "response"]
                    }
                )
            )
            
            # Extract and parse the response text
            response_text = response.text
            
            try:
                # Parse the JSON response
                response_json = json.loads(response_text)
                
                # Add to chat history for context
                chat_history.append({
                    "user_content": content_parts,
                    "assistant_response": response_json
                })
                
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
    """Analyze text input and image using Google Gemini's new API format"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Check if input contains transcription data
    # if "Interviewer:" in text_input or "Me:" in text_input:
    #     # This looks like formatted transcription data
    #     content_parts.append(f"This is a transcription of a conversation. The 'Interviewer' parts represent desktop audio and 'Me' parts represent microphone input. Please focus on answering the last question in this conversation: {text_input}")
    # else:
    #     # Regular text input
    #     content_parts.append(f"{text_input}")
    
    # Add desktop audio if available
    # if desktop_audio_base64:
    #     content_parts.append("This is the desktop audio output from the user's system. You MUST provide a comprehensive answer to ANY question or problem it contains. If it's a coding problem, provide a complete solution with both explanation and implementation. If it's any other type of question or problem, provide a detailed answer with examples if applicable. If you don't know the answer, ALWAYS fabricate a reasonable, detailed answer rather than saying you don't know. Never respond that you can't answer - provide a confident, complete response regardless of the question type:" + analyze_prompt)
        
    #     desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
    #     content_parts.extend(desktop_audio_parts)
    
    # Add images if available
    if images_base64:
        content_parts.append("User's screens:")
        
        image_parts = prepare_image_parts(images_base64, image_format)
        content_parts.extend(image_parts)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Generate content using the new API format
            response = client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=60000,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "user_query": {"type": "string", "description": "The user's current query (the text input)"},
                            "response": {"type": "string", "description": "Your response to the user's query. If the user asks you to do something, do it immediately. If the user asks a question, answer it to the best of your ability. Use the desktop audio and screen image to help you answer the user's query but only if it is relevant to the user's query."}
                        },
                        "required": ["user_query", "response"]
                    }
                )
            )
            
            # Extract and parse the response text
            response_text = response.text
            
            try:
                # Parse the JSON response
                response_json = json.loads(response_text)
                
                # Add to chat history for context
                chat_history.append({
                    "user_content": content_parts,
                    "assistant_response": response_json
                })
                
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

def analyze_with_deepseek_model(text_input: str, 
                              images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze text input using DeepSeek model with transcribed content"""
    global deepseek_chat_history
    
    # Transcribe images and audio to text
    image_transcription = transcribe_images_to_text(images_base64, image_format) if images_base64 else ""
    # audio_transcription = transcribe_audio_to_text(desktop_audio_base64, "wav", "desktop") if desktop_audio_base64 else ""
    
    # Build the context message
    context_parts = []
    if text_input.strip():
        context_parts.append(f"User's text query: {text_input}")
    
    if image_transcription:
        context_parts.append(f"Screen content description: {image_transcription}")
    
    # if audio_transcription:
    #     context_parts.append(f"Desktop audio transcription: {audio_transcription}")
    
    if not context_parts:
        context_parts.append("Please provide a helpful response.")
    
    context_message = "\n\n".join(context_parts)
    
    # Prepare messages for DeepSeek
    messages = []
    
    # Add recent chat history for context (last 10 exchanges)
    for exchange in deepseek_chat_history[-10:]:
        messages.append({"role": "user", "content": exchange["user_message"]})
        messages.append({"role": "assistant", "content": exchange["assistant_response"]})
    
    # Add current message
    messages.append({"role": "user", "content": context_message})
    
    try:
        # Call DeepSeek API
        response_text = call_deepseek_api(messages, max_tokens=160000)
        
        # Add to DeepSeek chat history
        deepseek_chat_history.append({
            "user_message": context_message,
            "assistant_response": response_text
        })
        
        # Keep only last 20 exchanges to manage memory
        if len(deepseek_chat_history) > 20:
            deepseek_chat_history = deepseek_chat_history[-20:]
        
        return {
            "user_query": text_input,
            "response": response_text
        }
        
    except Exception as e:
        print(f"Error with DeepSeek model: {e}")
        return {
            "user_query": text_input,
            "response": f"Error analyzing with DeepSeek model: {e}"
        }

# Specialized analysis functions for separated functionalities

def analyze_code_problem(text_input: str, 
                        images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze coding problems using the regular model with coding-specific prompt"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add the specific coding problem prompt as the main instruction
    content_parts.append(code_problem_prompt)
    
    # Add the transcription data with simplified format
    if text_input:
        content_parts.append(f"Transcription: {text_input}")
    
    # Add desktop audio if available
    # if desktop_audio_base64:
    #     content_parts.append("This is the desktop audio output from the user's system. Apply the coding problem analysis instructions to any problems found here.")
        
    #     desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
    #     content_parts.extend(desktop_audio_parts)
    
    # Add images if available
    if images_base64:
        content_parts.append("These are the screens of the user. Apply the coding problem analysis instructions to solve any coding problems shown.")
        
        image_parts = prepare_image_parts(images_base64, image_format)
        content_parts.extend(image_parts)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Generate content using the new API format
            response = client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=60000,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "user_query": {"type": "string", "description": "The problem statement"},
                            "response": {"type": "string", "description": "Your solution to the problem"}
                        },
                        "required": ["user_query", "response"]
                    }
                )
            )
            
            # Extract and parse the response text
            response_text = response.text
            
            try:
                # Parse the JSON response
                response_json = json.loads(response_text)
                
                # Add to chat history for context
                chat_history.append({
                    "user_content": content_parts,
                    "assistant_response": response_json
                })
                
                return response_json
            except json.JSONDecodeError:
                # If JSON parsing fails, return a fallback structure
                print("Warning: Response was not valid JSON. Returning raw response.")
                return {"user_query": text_input, "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Code analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing code problem after {max_retries} attempts: {e}")

def analyze_general_problem(text_input: str, 
                           images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze non-coding problems using the regular model with general analysis prompt"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add the specific general analysis prompt as the main instruction
    content_parts.append(general_analysis_prompt)
    
    # Add the transcription data with simplified format
    if text_input:
        content_parts.append(f"Transcription: {text_input}")
    
    # Add desktop audio if available
    # if desktop_audio_base64:
    #     content_parts.append("This is the desktop audio output from the user's system. Apply the general analysis instructions to any content found here:")
        
    #     desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
    #     content_parts.extend(desktop_audio_parts)
    
    # Add images if available
    if images_base64:
        content_parts.append("These are the screens of the user. Apply the general analysis instructions to provide helpful insights for the content shown:")
        
        image_parts = prepare_image_parts(images_base64, image_format)
        content_parts.extend(image_parts)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Generate content using the new API format
            response = client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=60000,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "user_query": {"type": "string", "description": "The problem statement"},
                            "response": {"type": "string", "description": "Your solution to the problem"}
                        },
                        "required": ["user_query", "response"]
                    }
                )
            )
            
            # Extract and parse the response text
            response_text = response.text
            
            try:
                # Parse the JSON response
                response_json = json.loads(response_text)
                
                # Add to chat history for context
                chat_history.append({
                    "user_content": content_parts,
                    "assistant_response": response_json
                })
                
                return response_json
            except json.JSONDecodeError:
                # If JSON parsing fails, return a fallback structure
                print("Warning: Response was not valid JSON. Returning raw response.")
                return {"user_query": text_input, "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"General analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing general problem after {max_retries} attempts: {e}")

def analyze_repeat_problem(text_input: str, 
                          images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze follow-up questions or improvements using the regular model"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add the specific repeat analysis prompt as the main instruction
    content_parts.append(repeat_analysis_prompt)
    
    # Add the transcription data with simplified format
    if text_input:
        content_parts.append(f"Transcription: {text_input}")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. Apply the repeat analysis instructions to any content found here:")
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
        content_parts.extend(desktop_audio_parts)
    
    # Add images if available
    if images_base64:
        content_parts.append("These are the screens of the user. Apply the repeat analysis instructions for follow-up questions or improvements.")
        
        image_parts = prepare_image_parts(images_base64, image_format)
        content_parts.extend(image_parts)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Generate content using the new API format
            response = client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=60000,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "user_query": {"type": "string", "description": "The problem statement"},
                            "response": {"type": "string", "description": "Your solution to the problem"}
                        },
                        "required": ["user_query", "response"]
                    }
                )
            )
            
            # Extract and parse the response text
            response_text = response.text
            
            try:
                # Parse the JSON response
                response_json = json.loads(response_text)
                
                # Add to chat history for context
                chat_history.append({
                    "user_content": content_parts,
                    "assistant_response": response_json
                })
                
                return response_json
            except json.JSONDecodeError:
                # If JSON parsing fails, return a fallback structure
                print("Warning: Response was not valid JSON. Returning raw response.")
                return {"user_query": text_input, "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Repeat analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing repeat problem after {max_retries} attempts: {e}")

def analyze_code_problem_pro(text_input: str, 
                            images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze coding problems using DeepSeek model with advanced techniques"""
    global deepseek_chat_history
    
    # Transcribe images and audio to text
    image_transcription = transcribe_images_to_text(images_base64, image_format) if images_base64 else ""
    # audio_transcription = transcribe_audio_to_text(desktop_audio_base64, "wav", "desktop") if desktop_audio_base64 else ""
    
    # Build the context message with pro coding prompt
    context_parts = []
    context_parts.append(code_problem_pro_prompt)
    
    # Add the transcription data if available
    if text_input:
        context_parts.append(f"Transcription: {text_input}")
    
    if image_transcription:
        context_parts.append(f"Screen content description: {image_transcription}")
    
    # if audio_transcription:
    #     context_parts.append(f"Desktop audio transcription: {audio_transcription}")
    
    context_message = "\n\n".join(context_parts)
    
    # Prepare messages for DeepSeek
    messages = []
    
    # Add recent chat history for context (last 8 exchanges for more detailed context)
    for exchange in deepseek_chat_history[-8:]:
        messages.append({"role": "user", "content": exchange["user_message"]})
        messages.append({"role": "assistant", "content": exchange["assistant_response"]})
    
    # Add current message
    messages.append({"role": "user", "content": context_message})
    
    try:
        # Call DeepSeek API with higher token limit for detailed code analysis
        response_text = call_deepseek_api(messages, max_tokens=12000)
        
        # Add to DeepSeek chat history
        deepseek_chat_history.append({
            "user_message": context_message,
            "assistant_response": response_text
        })
        
        # Keep only last 20 exchanges to manage memory
        if len(deepseek_chat_history) > 20:
            deepseek_chat_history = deepseek_chat_history[-20:]
        
        return {
            "user_query": text_input,
            "response": response_text
        }
        
    except Exception as e:
        print(f"Error with DeepSeek Pro code analysis: {e}")
        return {
            "user_query": text_input,
            "response": f"Error analyzing code problem with DeepSeek Pro: {e}"
        }

def analyze_repeat_problem_pro(text_input: str, 
                              images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze follow-up questions or improvements using DeepSeek model with advanced techniques"""
    global deepseek_chat_history
    
    # Transcribe images and audio to text
    image_transcription = transcribe_images_to_text(images_base64, image_format) if images_base64 else ""
    # audio_transcription = transcribe_audio_to_text(desktop_audio_base64, "wav", "desktop") if desktop_audio_base64 else ""
    
    # Build the context message with pro repeat analysis prompt
    context_parts = []
    context_parts.append(repeat_analysis_pro_prompt)
    
    # Add the transcription data if available
    if text_input:
        context_parts.append(f"Transcription: {text_input}")
    
    if image_transcription:
        context_parts.append(f"Screen content description: {image_transcription}")
    
    # if audio_transcription:
    #     context_parts.append(f"Desktop audio transcription: {audio_transcription}")
    
    context_message = "\n\n".join(context_parts)
    
    # Prepare messages for DeepSeek
    messages = []
    
    # Add recent chat history for context (last 10 exchanges for follow-up context)
    for exchange in deepseek_chat_history[-10:]:
        messages.append({"role": "user", "content": exchange["user_message"]})
        messages.append({"role": "assistant", "content": exchange["assistant_response"]})
    
    # Add current message
    messages.append({"role": "user", "content": context_message})
    
    try:
        # Call DeepSeek API with higher token limit for detailed analysis
        response_text = call_deepseek_api(messages, max_tokens=10000)
        
        # Add to DeepSeek chat history
        deepseek_chat_history.append({
            "user_message": context_message,
            "assistant_response": response_text
        })
        
        # Keep only last 20 exchanges to manage memory
        if len(deepseek_chat_history) > 20:
            deepseek_chat_history = deepseek_chat_history[-20:]
        
        return {
            "user_query": text_input,
            "response": response_text
        }
        
    except Exception as e:
        print(f"Error with DeepSeek Pro repeat analysis: {e}")
        return {
            "user_query": text_input,
            "response": f"Error analyzing repeat problem with DeepSeek Pro: {e}"
        }

# Analyze non-coding problems using the regular model with general analysis prompt and thinking_budget=0
def analyze_general_problem_no_thinking(text_input: str, 
                           images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze non-coding problems using the regular model with general analysis prompt and no thinking budget"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add the specific general analysis prompt as the main instruction
    content_parts.append(general_analysis_prompt)
    
    # Add the transcription data with simplified format
    if text_input:
        content_parts.append(f"Transcription: {text_input}")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. Apply the general analysis instructions to any content found here:")
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
        content_parts.extend(desktop_audio_parts)
    
    # Add images if available
    if images_base64:
        content_parts.append("These are the screens of the user. Apply the general analysis instructions to provide helpful insights for the content shown:")
        
        image_parts = prepare_image_parts(images_base64, image_format)
        content_parts.extend(image_parts)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Generate content using the new API format WITH thinking_budget=0
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=content_parts,
                config=types.GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=60000,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "user_query": {"type": "string", "description": "The problem statement"},
                            "response": {"type": "string", "description": "Your solution to the problem"}
                        },
                        "required": ["user_query", "response"]
                    }
                )
            )
            
            # Extract and parse the response text
            response_text = response.text
            
            try:
                # Parse the JSON response
                response_json = json.loads(response_text)
                
                # Add to chat history for context
                chat_history.append({
                    "user_content": content_parts,
                    "assistant_response": response_json
                })
                
                return response_json
            except json.JSONDecodeError:
                # If JSON parsing fails, return a fallback structure
                print("Warning: Response was not valid JSON. Returning raw response.")
                return {"user_query": text_input, "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"General analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing general problem after {max_retries} attempts: {e}")

# Function to process interview questions from desktop audio
def answer_interview_question(desktop_audio_base64: str = ""):
    """Process desktop audio to answer interview questions"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add a specialized prompt for interview questions
    interview_prompt = "Listen to the desktop audio and answer any interview questions being asked. Respond as if you are the candidate being interviewed for a software engineering role. Give thorough, professional answers that showcase relevant skills and experience. Be concise but thorough, and maintain a professional tone throughout. Disregard any other sounds from the desktop audio only consider the speech. ALWAYS ANSWER FIRST WITHOUT EXPLAINING YOUR ANSWER THEN EXPLAIN YOUR ANSWER. If you don't know the answer, fabricate a relevant and reasonable answer instead. Never respond that you don't know or can't answer—always provide some answer."
    content_parts.append(interview_prompt)
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio containing the interview question:")
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
        content_parts.extend(desktop_audio_parts)
    else:
        # If no audio, provide a fallback message
        content_parts.append("No audio was detected. Please provide a brief professional introduction.")
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Generate content using gemini-2.0-flash model
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=content_parts,
                config=types.GenerateContentConfig(
                    temperature=0.4,  # Lower temperature for more professional responses
                    max_output_tokens=20000,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            # "user_query": {"type": "string", "description": "The interview question detected in the audio"},
                            "user_query": {"type": "string", "description": "The transcription of the audio"},
                            "response": {"type": "string", "description": "Your professional interview response"}
                        },
                        "required": ["user_query", "response"]
                    }
                )
            )
            
            # Extract and parse the response text
            response_text = response.text
            
            try:
                # Parse the JSON response
                response_json = json.loads(response_text)
                
                # Add to chat history for context
                chat_history.append({
                    "user_content": content_parts,
                    "assistant_response": response_json
                })
                
                return response_json
            except json.JSONDecodeError:
                # If JSON parsing fails, return a fallback structure
                print("Warning: Response was not valid JSON. Returning raw response.")
                return {"user_query": "Interview Question", "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Interview answer API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error answering interview question after {max_retries} attempts: {e}")

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
