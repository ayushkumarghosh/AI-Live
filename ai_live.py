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
from PyQt5 import QtWidgets, QtCore
from overlay import DraggableOverlay

# Initialize chat history
chat_history = ChatHistory()

# Audio queue for communication between threads
audio_queue = queue.Queue()

# Global reference to the overlay
overlay = None

# Rate limiting settings - 30 RPM = 1 request per 2 seconds to be safe
RATE_LIMIT = 2.0  # seconds between requests
last_request_time = 0
api_semaphore = threading.Semaphore(1)  # Allow only 1 API call at a time

def capture_screenshot(max_width=1280, quality=85):
    """Capture a screenshot, resize it, and return it as a base64 encoded string"""
    screenshot = ImageGrab.grab()
    
    # Resize the image to reduce size while maintaining aspect ratio
    orig_width, orig_height = screenshot.size
    if orig_width > max_width:
        ratio = max_width / float(orig_width)
        new_height = int(orig_height * ratio)
        screenshot = screenshot.resize((max_width, new_height), resample=1)
    
    # Save with compression to reduce size
    img_bytes = io.BytesIO()
    screenshot.save(img_bytes, format='JPEG', quality=quality, optimize=True)
    img_bytes.seek(0)
    
    return base64.b64encode(img_bytes.getvalue()).decode('utf-8')

def audio_recorder():
    """Run recording and put data into the queue"""
    # Create a queue for the audio recorder
    recorder_queue = queue.Queue()
    
    # Start recording in a separate thread
    recording_thread = threading.Thread(
        target=record_speech,
        args=(recorder_queue,),
        daemon=True
    )
    recording_thread.start()
    
    global overlay
    
    while True:
        # Get audio data from recorder queue
        audio_data = recorder_queue.get()
        if audio_data is not None:
            # Put data into the processing queue
            audio_queue.put(audio_data)
        recorder_queue.task_done()

def process_audio_data():
    """Process audio segments in a dedicated thread"""
    global overlay
    
    print("\n" + "=" * 50, flush=True)
    print("🎙️  AI LIVE SYSTEM STARTED 🎙️", flush=True)
    print("=" * 50 + "\n", flush=True)
    
    while True:
        try:
            # Wait for audio data
            audio_data = audio_queue.get()
            
            sys.stdout.flush()
            
            try:
                # Capture screenshot
                screenshot_base64 = capture_screenshot()
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎙️ Audio received, processing...", flush=True)
                sys.stdout.flush()
                if overlay:
                    overlay.update_status("Processing...", "#FFA500")
                
                # Process each speech input with rate limiting
                analyze_with_streaming(chat_history, audio_data, screenshot_base64)
            
            except Exception as e:
                print(f"Error processing audio: {e}", flush=True)
                if overlay:
                    overlay.update_status("Error", "#FF0000")
            
            # Mark task as done
            audio_queue.task_done()
        except Exception as e:
            print(f"Error in process_task: {e}", flush=True)
            time.sleep(0.1)  # Prevent tight loop on error

def analyze_with_streaming(chat_history, audio_data, screenshot_base64):
    """Analyze audio and image and return complete response"""
    global overlay
    
    try:
        sys.stdout.flush()
        full_response = ""
        # Apply rate limiting with semaphore
        with api_semaphore:
            # Check if we need to wait to respect the rate limit
            global last_request_time
            current_time = time.time()
            time_since_last_request = current_time - last_request_time
            
            if time_since_last_request < RATE_LIMIT:
                wait_time = RATE_LIMIT - time_since_last_request
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏱️ Rate limiting: waiting {wait_time:.2f}s", flush=True)
                time.sleep(wait_time)
            
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
            
            # Collect the complete response
            for chunk in response:
                if chunk.text:
                    full_response += chunk.text
            
            # Print the complete response
            print(full_response, flush=True)
            print("\n" + "-" * 50, flush=True)
            
            # Add to chat history
            chat_history.add_entry(mic_audio, full_response, screenshot_base64, desktop_audio)
            
            sys.stdout.flush()
        # Update overlay with complete response
        if overlay:
            overlay.update_response(full_response)
            overlay.update_status("Listening...", "#4CAF50")
    
    except Exception as e:
        print(f"Error in analysis: {e}", flush=True)
        if overlay:
            overlay.update_status("Error", "#FF0000")
            overlay.update_response(f"Error: {str(e)}")
        sys.stdout.flush()

def main():
    # Create Qt application
    app = QtWidgets.QApplication(sys.argv)
    
    # Create and show the overlay
    global overlay
    overlay = DraggableOverlay()
    overlay.show()
    
    # Start the audio recorder in a separate thread
    audio_recorder_thread = threading.Thread(
        target=audio_recorder,
        daemon=True
    )
    audio_recorder_thread.start()
    
    # Start the audio processing in a separate thread
    processing_thread = threading.Thread(
        target=process_audio_data,
        daemon=True
    )
    processing_thread.start()
    
    # Run the Qt event loop
    app.exec_()

if __name__ == "__main__":
    main()