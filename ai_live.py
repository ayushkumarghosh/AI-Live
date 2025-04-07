import asyncio
import queue
from datetime import datetime
from speech_capture import record_speech
from chat import analyze_with_audio_and_image, ChatHistory, process_stream_response
import base64
import io
from PIL import ImageGrab
import sys
import threading
import time

# Initialize chat history
chat_history = ChatHistory()

# Audio queue for communication between sync and async parts
audio_queue = asyncio.Queue()

# Global reference to the main event loop (will be set in main)
main_loop = None

# Rate limiting settings - 30 RPM = 1 request per 2 seconds to be safe
RATE_LIMIT = 2.0  # seconds between requests
last_request_time = 0
api_semaphore = asyncio.Semaphore(1)  # Allow only 1 API call at a time

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
    
    while True:
        # Wait for audio data
        audio_data = await audio_queue.get()
        
        sys.stdout.flush()
        
        try:
            # Capture screenshot
            screenshot_base64 = capture_screenshot()
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎙️ Audio received, processing...", flush=True)
            sys.stdout.flush()
            
            # Process each speech input with rate limiting
            asyncio.create_task(
                analyze_with_streaming(chat_history, audio_data, screenshot_base64)
            )
        
        except Exception as e:
            print(f"Error processing audio: {e}", flush=True)
        
        # Mark task as done
        audio_queue.task_done()

async def analyze_with_streaming(chat_history, audio_data, screenshot_base64):
    """Analyze audio and image with streaming response"""
    try:
        sys.stdout.flush()
        
        # Apply rate limiting with semaphore
        async with api_semaphore:
            # Check if we need to wait to respect the rate limit
            global last_request_time
            current_time = time.time()
            time_since_last_request = current_time - last_request_time
            
            if time_since_last_request < RATE_LIMIT:
                wait_time = RATE_LIMIT - time_since_last_request
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏱️ Rate limiting: waiting {wait_time:.2f}s", flush=True)
                await asyncio.sleep(wait_time)
            
            # Update the last request time
            last_request_time = time.time()
            
            # Extract microphone and desktop audio
            mic_audio = audio_data.get("mic_audio", "")
            desktop_audio = audio_data.get("desktop_audio", "")
            
            # Log if we have desktop audio
            if desktop_audio:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔊 Desktop audio captured and included", flush=True)
            
            # Start the analysis request
            response = analyze_with_audio_and_image(
                chat_history, 
                mic_audio, 
                "wav", 
                screenshot_base64, 
                "jpeg", 
                desktop_audio
            )
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 💬 AI response:", flush=True)
            print("-" * 50, flush=True)
            sys.stdout.flush()
            
            # Process the streaming response using the function from chat.py
            full_response = process_stream_response(response)
            
            print("\n" + "-" * 50, flush=True)
            sys.stdout.flush()
            
            # Add to chat history - we store the microphone audio in the history
            chat_history.add_entry(mic_audio, full_response, screenshot_base64, desktop_audio)
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