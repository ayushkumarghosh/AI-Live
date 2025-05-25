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

# Google Gemini API setup
gemini_api_key = os.getenv("GEMINI_API")

# Initialize the new GenAI client
client = genai.Client(api_key=gemini_api_key)

# Model names
GEMINI_FLASH_MODEL = "gemini-2.5-flash-preview-05-20"
GEMINI_PRO_MODEL = "gemini-2.5-pro-exp-03-25"

# Separated prompts for different functionalities

# 1. Code problem analysis prompt (regular model)
code_problem_prompt = "Analyze the desktop audio (if any) along with the screenshots to solve coding problems. If the screenshot or desktop audio contains a coding problem, provide a complete working solution as follows: For a new/first-time question, first briefly explain both the naive approach and the optimized approach (without code), THEN implement both approaches with complete code. If the screenshot shows a LeetCode-like interface or any code cell with an existing code snippet, always use both the programming language shown and the code snippet itself as your starting point: directly modify, extend, or complete that code rather than starting from scratch or ignoring it. Ensure any code is ready to submit with no missing parts. Always be thorough and complete in your response."

# 2. Non-coding problem analysis prompt (regular model)
general_analysis_prompt = "Analyze the desktop audio (if any) along with the screenshots and provide a helpful response for non-coding content. Provide a detailed analysis relevant to what's shown in the screenshot. This could include explaining concepts, answering questions, providing insights, or helping with general tasks. If you don't have a clear answer, fabricate a reasonable and relevant answer instead. Never respond that you don't know or can't answer - always provide some answer. Always be thorough and complete in your response."

# 3. Repeat analysis prompt (regular model) 
repeat_analysis_prompt = "Analyze the desktop audio (if any) along with the screenshots for follow-up questions or improvements to an existing solution. Briefly explain the improvement first, then focus on implementing the improved optimized solution - don't repeat the naive approach again. If this is a coding problem, provide the enhanced solution with proper explanation. For non-coding content, provide updated or refined analysis based on the new context. Always be thorough and complete in your response."

# 4. Code problem analysis prompt (pro model)
code_problem_pro_prompt = "Analyze the screenshot and desktop audio (if any) and focus on solving any coding problem shown using advanced techniques. If the screenshot shows a LeetCode-like interface or any code with an existing code snippet, always use both the programming language shown and the code snippet itself as your starting point: directly modify, extend, or complete that code rather than starting from scratch or ignoring it. Follow these steps: (1) If there's code in the screenshot, understand what it's trying to do and its context, (2) Explain your optimized approach as if explaining to an interviewer - clearly articulate the time and space complexity, trade-offs, and logic behind your solution, (3) Implement the complete optimized solution with proper edge case handling and clean, well-commented code. Always be thorough and provide production-ready solutions."

# 5. Repeat analysis prompt (pro model)
repeat_analysis_pro_prompt = "Analyze the screenshot and desktop audio (if any) for follow-up questions or improvements to coding problems using the Pro model. Focus on implementing enhanced, optimized solutions with advanced algorithms and techniques. Explain the improvements, time and space complexity optimizations, and provide production-ready code with comprehensive error handling. Always be thorough and provide expert-level solutions."

# Legacy prompts (kept for backwards compatibility)
analyze_prompt = code_problem_prompt  # Default to code problem analysis
super_analyze_prompt = code_problem_pro_prompt  # Default to pro code analysis

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

def clear_chat_history():
    """Clear the chat history and start fresh"""
    global chat_history
    chat_history = []
    print(f"{timestamp()} Chat history cleared")
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
    
    # Add explanatory text for the user's text input
    content_parts.append(f"This is the user's query (typed text), always prioritize it: {text_input}")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. You MUST provide a comprehensive answer to ANY question or problem it contains. If it's a coding problem, provide a complete solution with both explanation and implementation. If it's any other type of question or problem, provide a detailed answer with examples if applicable. If you don't know the answer, ALWAYS fabricate a reasonable, detailed answer rather than saying you don't know. Never respond that you can't answer - provide a confident, complete response regardless of the question type:" + analyze_prompt)
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
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
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add explanatory text for the user's text input
    content_parts.append(f"This is the user's query (typed text), always prioritize it: {text_input}")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. You MUST provide a comprehensive answer to ANY question or problem it contains. If it's a coding problem, provide a complete solution with both explanation and implementation. If it's any other type of question or problem, provide a detailed answer with examples if applicable. If you don't know the answer, ALWAYS fabricate a reasonable, detailed answer rather than saying you don't know. Never respond that you can't answer - provide a confident, complete response regardless of the question type:" + super_analyze_prompt)
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
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
            # Generate content using the new API format with Pro model
            response = client.models.generate_content(
                model=GEMINI_PRO_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    max_output_tokens=65536
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
                print("Warning: Pro model response was not valid JSON. Returning raw response.")
                return {"user_query": text_input, "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Pro analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing with Pro model after {max_retries} attempts: {e}")

# Specialized analysis functions for separated functionalities

def analyze_code_problem(text_input: str, 
                        images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze coding problems using the regular model with coding-specific prompt"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add the specific coding problem prompt as the main instruction
    content_parts.append(code_problem_prompt)
    
    # Add explanatory text for the user's text input
    content_parts.append(f"This is the user's query (typed text), always prioritize it: {text_input}")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. Apply the coding problem analysis instructions to any problems found here.")
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
        content_parts.extend(desktop_audio_parts)
    
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
                            "user_query": {"type": "string", "description": "The user's current query (the text input)"},
                            "response": {"type": "string", "description": "Your response focused on solving coding problems"}
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
    
    # Add explanatory text for the user's text input
    content_parts.append(f"This is the user's query (typed text), always prioritize it: {text_input}")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. Apply the general analysis instructions to any content found here.")
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
        content_parts.extend(desktop_audio_parts)
    
    # Add images if available
    if images_base64:
        content_parts.append("These are the screens of the user. Apply the general analysis instructions to provide helpful insights for the content shown.")
        
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
                            "response": {"type": "string", "description": "Your response focused on general analysis and helpful insights"}
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
    
    # Add explanatory text for the user's text input
    content_parts.append(f"This is the user's query (typed text), always prioritize it: {text_input}")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. Apply the repeat analysis instructions to any content found here.")
        
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
                            "user_query": {"type": "string", "description": "The user's current query (the text input)"},
                            "response": {"type": "string", "description": "Your response focused on follow-up analysis and improvements"}
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
    """Analyze coding problems using the Pro model with advanced techniques"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add the specific pro coding problem prompt as the main instruction
    content_parts.append(code_problem_pro_prompt)
    
    # Add explanatory text for the user's text input
    content_parts.append(f"This is the user's query (typed text), always prioritize it: {text_input}")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. Apply the advanced coding problem analysis instructions to any problems found here.")
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
        content_parts.extend(desktop_audio_parts)
    
    # Add images if available
    if images_base64:
        content_parts.append("These are the screens of the user. Apply the advanced coding problem analysis instructions to solve coding problems with expert-level techniques.")
        
        image_parts = prepare_image_parts(images_base64, image_format)
        content_parts.extend(image_parts)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Generate content using the new API format with Pro model
            response = client.models.generate_content(
                model=GEMINI_PRO_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    max_output_tokens=65536
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
                print("Warning: Pro model response was not valid JSON. Returning raw response.")
                return {"user_query": text_input, "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Pro code analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing code problem with Pro model after {max_retries} attempts: {e}")

def analyze_repeat_problem_pro(text_input: str, 
                              images_base64: List[str], image_format: str, desktop_audio_base64: str = ""):
    """Analyze follow-up questions or improvements using the Pro model with advanced techniques"""
    global chat_history
    
    # Prepare content parts
    content_parts = []
    
    # Add the specific pro repeat analysis prompt as the main instruction
    content_parts.append(repeat_analysis_pro_prompt)
    
    # Add explanatory text for the user's text input
    content_parts.append(f"This is the user's query (typed text), always prioritize it: {text_input}")
    
    # Add desktop audio if available
    if desktop_audio_base64:
        content_parts.append("This is the desktop audio output from the user's system. Apply the advanced repeat analysis instructions to any content found here.")
        
        desktop_audio_parts = prepare_audio_parts(desktop_audio_base64, "wav", "desktop")
        content_parts.extend(desktop_audio_parts)
    
    # Add images if available
    if images_base64:
        content_parts.append("These are the screens of the user. Apply the advanced repeat analysis instructions for expert-level follow-up solutions and optimizations.")
        
        image_parts = prepare_image_parts(images_base64, image_format)
        content_parts.extend(image_parts)
    
    # Implement retry logic
    max_retries = 3
    retry_delay = 1
    
    for retry in range(max_retries):
        try:
            # Generate content using the new API format with Pro model
            response = client.models.generate_content(
                model=GEMINI_PRO_MODEL,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    max_output_tokens=65536
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
                print("Warning: Pro model response was not valid JSON. Returning raw response.")
                return {"user_query": text_input, "response": response_text}
                
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Pro repeat analysis API request failed (attempt {retry+1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                # This was the last attempt, raise the exception
                raise Exception(f"Error analyzing repeat problem with Pro model after {max_retries} attempts: {e}")

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
