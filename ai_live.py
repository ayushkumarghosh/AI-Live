import asyncio
import queue
from datetime import datetime
from speech_capture import record_speech
from pollinations import transcribe, analyze_image_with_history, ChatHistory, encode_image_base64
import time
import base64
import io
import json
import sseclient
from PIL import ImageGrab
import sys
import threading

# Initialize chat history
chat_history = ChatHistory()

# Audio queue for communication between sync and async parts
audio_queue = asyncio.Queue()

# Event for cancellation
cancel_event = asyncio.Event()

# Global reference to the main event loop (will be set in main)
main_loop = None

def capture_screenshot(max_width=1280, quality=85):
    """Capture a screenshot, resize it, and return it as a base64 encoded string"""
    screenshot = ImageGrab.grab()
    
    # Resize the image to reduce size while maintaining aspect ratio
    orig_width, orig_height = screenshot.size
    if orig_width > max_width:
        ratio = max_width / float(orig_width)
        new_height = int(orig_height * ratio)
        screenshot = screenshot.resize((max_width, new_height), resample=1)  # Using PIL.Image.LANCZOS (1) for high-quality downsampling
    
    # Save with compression to reduce size
    img_bytes = io.BytesIO()
    screenshot.save(img_bytes, format='JPEG', quality=quality, optimize=True)
    img_bytes.seek(0)
    
    # Get the size for logging
    size_kb = len(img_bytes.getvalue()) / 1024
    # print(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Screenshot captured: {size_kb:.2f} KB", flush=True)
    
    return base64.b64encode(img_bytes.getvalue()).decode('utf-8')

def sync_audio_recorder():
    """Run recording in synchronous mode and put data into async queue"""
    # print("Starting audio recording thread...", flush=True)
    # Create a synchronous queue for the audio recorder
    sync_queue = queue.Queue()
    
    # Start recording in a separate thread
    recording_thread = threading.Thread(
        target=record_speech,
        args=(sync_queue,),
        daemon=True
    )
    recording_thread.start()
    
    # Use the global main_loop reference
    global main_loop
    
    while True:
        # Get audio data from sync queue
        audio_data = sync_queue.get()
        if audio_data is not None:
            # Use run_coroutine_threadsafe to safely put data into the async queue
            # using the main event loop
            asyncio.run_coroutine_threadsafe(audio_queue.put(audio_data), main_loop)
        sync_queue.task_done()

async def process_audio_data():
    """Process audio segments asynchronously"""
    print("\n" + "=" * 50, flush=True)
    print("🎙️  AI LIVE SYSTEM STARTED 🎙️", flush=True)
    print("=" * 50 + "\n", flush=True)
    
    # Start the transcription and analysis
    current_task = None
    
    while True:
        # Wait for audio data
        audio_data = await audio_queue.get()
        
        sys.stdout.flush()
        
        try:
            # Transcribe audio
            transcription = transcribe(audio_data, "wav")
            
            # Handle different transcription results
            if "error500" in transcription or transcription == "":
                pass
            elif "error400" in transcription:
                print("Sorry, I didn't get that. Could you please repeat?", flush=True)
            elif transcription:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 User: \"{transcription}\"", flush=True)
                sys.stdout.flush()
                
                # Capture screenshot
                # print(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Capturing screenshot...")
                screenshot_base64 = capture_screenshot()
                
                # Cancel any ongoing analysis
                if current_task and not current_task.done():
                    cancel_event.set()
                    try:
                        # Wait a short time for the task to cancel itself
                        await asyncio.wait_for(current_task, timeout=0.5)
                    except asyncio.TimeoutError:
                        # Force cancel if it doesn't respond
                        current_task.cancel()
                    
                    # Clear the event for next use
                    cancel_event.clear()
                
                # Start a new analysis task
                current_task = asyncio.create_task(
                    analyze_with_streaming(chat_history, screenshot_base64, transcription)
                )
        
        except Exception as e:
            print(f"Error processing audio: {e}", flush=True)
        
        # Mark task as done
        audio_queue.task_done()

async def analyze_with_streaming(chat_history, screenshot_base64, transcription):
    """Analyze image and transcript with streaming response"""
    try:
        sys.stdout.flush()
        
        # Start the analysis request
        response = analyze_image_with_history(chat_history, screenshot_base64, "jpeg", transcription)
        
        # Process the streaming response
        client = sseclient.SSEClient(response)
        full_response = ""
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 💬 AI response:", flush=True)
        print("-" * 50, flush=True)
        sys.stdout.flush()
        
        for event in client.events():
            # Check if we should cancel
            if cancel_event.is_set():
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Analysis interrupted for new transcription", flush=True)
                try:
                    response.close()
                except:
                    pass
                return
            
            if event.data:
                try:
                    # Handle potential '[DONE]' marker
                    if event.data.strip() == '[DONE]':
                        print("\n" + "-" * 50, flush=True)
                        # print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Stream finished.", flush=True)
                        sys.stdout.flush()
                        break
                    
                    chunk = json.loads(event.data)
                    content = None
                    if len(chunk.get('choices', [{}])) > 0:
                        content = chunk.get('choices', [{}])[0].get('delta', {}).get('content')
                    
                    if content:
                        # Print character by character for better streaming
                        for char in content:
                            print(char, end='', flush=True)
                            sys.stdout.flush()
                            # Allow a very brief moment for the OS to flush output
                            await asyncio.sleep(0.0005)
                        
                        full_response += content
                        
                except json.JSONDecodeError:
                    print(f"\nReceived non-JSON data: {event.data}", flush=True)
                    sys.stdout.flush()
                
                # Yield control to allow other tasks to run
                await asyncio.sleep(0)
        
        # Add to chat history if completed successfully
        if not cancel_event.is_set():
            response_obj = {"choices": [{"message": {"content": full_response}}]}
            chat_history.add_entry(transcription, response_obj, screenshot_base64)
            # print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Analysis complete", flush=True)
            sys.stdout.flush()
    
    except Exception as e:
        print(f"Error in analysis: {e}", flush=True)
        sys.stdout.flush()

async def main():
    # Store the main event loop reference globally
    global main_loop
    main_loop = asyncio.get_running_loop()
    
    # Start the audio bridge in a separate thread
    audio_thread = threading.Thread(
        target=sync_audio_recorder,
        daemon=True
    )
    audio_thread.start()
    
    # Run the main processing task
    await process_audio_data()

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())