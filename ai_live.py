import queue
from datetime import datetime
from speech_capture import record_speech
from chat import analyze_with_audio_and_image, analyze_with_text_input, ChatHistory
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
    
    # Keep track of processed audio hashes to prevent duplicates
    processed_hashes = set()
    
    # Track the latest input - we only keep the most recent one
    latest_pending_input = None
    
    # Flag to track if we're currently processing
    is_processing = False
    
    # Create a fingerprint of the audio data for better deduplication
    def get_audio_fingerprint(audio_data):
        if not audio_data or "mic_audio" not in audio_data:
            return None
        
        mic_audio = audio_data.get("mic_audio", "")
        if len(mic_audio) < 100:
            return None
            
        # Use a more robust fingerprint based on multiple segments of the audio
        if len(mic_audio) > 6000:
            # Take samples from beginning, middle and end for a more robust fingerprint
            fingerprint = hash(mic_audio[:2000] + mic_audio[len(mic_audio)//2-1000:len(mic_audio)//2+1000] + mic_audio[-2000:])
        else:
            fingerprint = hash(mic_audio)
        
        return fingerprint
    
    while True:
        try:
            # Wait for audio data
            audio_data = audio_queue.get()
            
            sys.stdout.flush()
            
            try:
                # Get audio fingerprint for deduplication
                audio_fingerprint = get_audio_fingerprint(audio_data)
                
                # Skip if we've already processed this audio or if it's invalid
                if audio_fingerprint is None:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Invalid audio data received, skipping", flush=True)
                    audio_queue.task_done()
                    continue
                    
                if audio_fingerprint in processed_hashes:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Duplicate audio fingerprint detected, skipping", flush=True)
                    audio_queue.task_done()
                    continue
                
                # Check if we're currently processing another input
                if is_processing:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏳ Already processing another request, storing as latest input", flush=True)
                    
                    # Store only the most recent pending input
                    latest_pending_input = {
                        "timestamp": datetime.now(),
                        "fingerprint": audio_fingerprint,
                        "audio_data": audio_data
                    }
                    
                    audio_queue.task_done()
                    continue
                
                # Mark as processing to prevent concurrent processing
                is_processing = True
                
                # Capture screenshot
                screenshot_base64 = capture_screenshot()
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎙️ Audio received, processing...", flush=True)
                sys.stdout.flush()
                if overlay:
                    overlay.update_status("Processing...", "#FFA500")
                    overlay.set_processing(True)
                
                # Add to processed hashes before processing to prevent duplicates
                processed_hashes.add(audio_fingerprint)
                
                # Limit the size of the processed_hashes set to prevent memory growth
                if len(processed_hashes) > 100:
                    # Keep only the 50 most recent hashes
                    processed_hashes = set(list(processed_hashes)[-50:])
                
                # Process audio input
                analyze_with_streaming(chat_history, audio_data, screenshot_base64)
                
                # Set processing done flag
                if overlay:
                    overlay.set_processing(False)
                
                # Only after successful completion, check for pending input
                pending_input = latest_pending_input
                latest_pending_input = None
                
                # Mark as no longer processing
                is_processing = False
                
                # Process pending input if there is one
                if pending_input:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📋 Processing latest pending input", flush=True)
                    
                    # Only process if we haven't already processed this hash
                    if pending_input["fingerprint"] not in processed_hashes:
                        # Add to processed hashes
                        processed_hashes.add(pending_input["fingerprint"])
                        
                        # Put back in the queue for fresh processing
                        audio_queue.put(pending_input["audio_data"])
                    else:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Pending input was already processed, skipping", flush=True)
            
            except Exception as e:
                print(f"Error processing audio: {e}", flush=True)
                if overlay:
                    overlay.update_status("Error", "#FF0000")
                    overlay.set_processing(False)
                is_processing = False
            
            # Mark task as done
            audio_queue.task_done()
        except Exception as e:
            print(f"Error in process_task: {e}", flush=True)
            is_processing = False
            time.sleep(0.1)  # Prevent tight loop on error

def analyze_with_streaming(chat_history, audio_data, screenshot_base64):
    """Analyze audio and image and return complete response"""
    global overlay
    
    # Generate a session ID for this analysis
    session_id = f"session_{datetime.now().strftime('%H%M%S')}_{hash(str(audio_data))}"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🆔 Processing session {session_id}", flush=True)
    
    try:
        sys.stdout.flush()
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
            
            # Debug audio data
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Debug - session {session_id} - mic_audio type: {type(mic_audio).__name__}, length: {len(str(mic_audio))}", flush=True)
            if len(str(mic_audio)) < 100:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Warning: Microphone audio data may be too short or empty", flush=True)
            
            # Make sure audio data is valid base64 for API
            try:
                # Validate that the audio data is properly base64 encoded
                base64.b64decode(mic_audio)
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Warning: Invalid base64 audio data: {e}", flush=True)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Attempting to fix or skip audio data", flush=True)
                # Provide a fallback text for cases where the audio data is invalid
                result = {"user_query": "Audio data error", "response": "I couldn't process your audio. Please try again or use text input."}
                
                # Update overlay with the error response
                if overlay:
                    overlay.update_response(result)
                    overlay.update_status("Listening...", "#4CAF50")
                
                return result
            
            # Start the analysis request
            response_json = analyze_with_audio_and_image(
                chat_history, 
                mic_audio, 
                "wav", 
                screenshot_base64, 
                "jpeg", 
                desktop_audio
            )
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 💬 AI response for session {session_id}:", flush=True)
            print("-" * 50, flush=True)
            sys.stdout.flush()
            
            # Extract the user query and response
            user_query = response_json.get("user_query", "Could not extract query")
            ai_response = response_json.get("response", "No response generated")
            
            # Print the complete response
            print(f"User's query: {user_query}\n")
            print(f"AI response: {ai_response}", flush=True)
            print("\n" + "-" * 50, flush=True)
            
            # Add to chat history
            chat_history.add_entry(mic_audio, ai_response, screenshot_base64, desktop_audio)
            
            sys.stdout.flush()
            
            # Update overlay with structured response
            if overlay:
                overlay.update_response(response_json)
                overlay.update_status("Listening...", "#4CAF50")
            
            return response_json
    
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error in analysis session {session_id}: {e}", flush=True)
        if overlay:
            overlay.update_status("Error", "#FF0000")
            error_response = {"user_query": "Error occurred", "response": f"Error: {str(e)}"}
            overlay.update_response(error_response)
        sys.stdout.flush()
        return error_response

def process_text_input(text_input):
    """Process text input from the overlay UI"""
    global overlay
    
    try:
        # Check if we're already processing something
        if overlay and overlay.is_processing:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Already processing another request, ignoring text input", flush=True)
            return
        
        # Set processing state
        if overlay:
            overlay.set_processing(True)
        
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
            
            # Capture screenshot
            screenshot_base64 = capture_screenshot()
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 💬 Text input received: {text_input}", flush=True)
            
            # Get desktop audio from speech_capture
            from speech_capture import get_desktop_speech_segments
            desktop_audio = get_desktop_speech_segments()
            if desktop_audio:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔊 Desktop audio captured and included", flush=True)
            
            # Process the text input
            response_json = analyze_with_text_input(
                chat_history,
                text_input,
                screenshot_base64,
                "jpeg",
                desktop_audio
            )
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 💬 AI response:", flush=True)
            print("-" * 50, flush=True)
            sys.stdout.flush()
            
            # Extract the user query and response
            user_query = response_json.get("user_query", text_input)
            ai_response = response_json.get("response", "No response generated")
            
            # Print the complete response
            print(f"User's query: {user_query}\n")
            print(f"AI response: {ai_response}", flush=True)
            print("\n" + "-" * 50, flush=True)
            
            # Add to chat history - using empty string for audio since this was text input
            chat_history.add_entry("", ai_response, screenshot_base64, desktop_audio)
            
            # Update overlay with structured response
            if overlay:
                overlay.update_response(response_json)
                overlay.update_status("Listening...", "#4CAF50")
            
            sys.stdout.flush()
    
    except Exception as e:
        print(f"Error processing text input: {e}", flush=True)
        if overlay:
            overlay.update_status("Error", "#FF0000")
            overlay.update_response({"user_query": text_input, "response": f"Error: {str(e)}"})
    
    finally:
        # Always reset processing state when done
        if overlay:
            overlay.set_processing(False)

def main():
    # Create Qt application
    app = QtWidgets.QApplication(sys.argv)
    
    # Create and show the overlay
    global overlay
    overlay = DraggableOverlay()
    overlay.show()
    
    # Connect the text_submitted signal to the process_text_input function
    overlay.text_submitted.connect(process_text_input)
    
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