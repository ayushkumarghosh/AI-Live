import queue
from datetime import datetime
from speech_capture import record_speech
from chat import analyze_with_audio_and_image, analyze_with_text_input
import base64
import io
from PIL import ImageGrab
import sys
import threading
import time
from PyQt6 import QtWidgets, QtCore
from overlay import DraggableOverlay
import wave
import concurrent.futures

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

    # Flag to track if we're currently processing
    is_processing = False

    # Track previous mic state to detect changes
    prev_mic_enabled = True

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

    # Function to merge multiple audio data objects into one
    def merge_audio_data(audio_data_list):
        """Merge multiple audio data objects into a single one"""
        if not audio_data_list:
            return None
        
        if len(audio_data_list) == 1:
            return audio_data_list[0]
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Merging {len(audio_data_list)} audio inputs together", flush=True)
        
        # Extract all microphone audio segments
        all_mic_segments = []
        # Use the desktop audio from the latest sample
        desktop_audio = audio_data_list[-1].get("desktop_audio", "")
        
        for data in audio_data_list:
            mic_audio = data.get("mic_audio", "")
            if mic_audio and len(mic_audio) > 100:
                try:
                    # Validate base64 data
                    audio_bytes = base64.b64decode(mic_audio)
                    all_mic_segments.append(audio_bytes)
                except Exception as e:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Error decoding audio: {e}", flush=True)
        
        if not all_mic_segments:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] No valid audio segments to merge", flush=True)
            return audio_data_list[-1]  # Return the last one as fallback
        
        # Merge all mic segments into one WAV file
        try:
            # Create a new WAV file in memory
            combined_wav = io.BytesIO()
            
            # Read the first WAV file to get format information
            with wave.open(io.BytesIO(all_mic_segments[0]), 'rb') as first_wav:
                channels = first_wav.getnchannels()
                sample_width = first_wav.getsampwidth()
                framerate = first_wav.getframerate()
            
            # Create the output WAV file with the same format
            with wave.open(combined_wav, 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(sample_width)
                wf.setframerate(framerate)
                
                # Write all segments to the WAV file
                for segment_data in all_mic_segments:
                    # Extract audio frames from the WAV file
                    with wave.open(io.BytesIO(segment_data), 'rb') as segment_wav:
                        wf.writeframes(segment_wav.readframes(segment_wav.getnframes()))
            
            # Get the merged WAV as base64
            combined_wav.seek(0)
            merged_mic_audio = base64.b64encode(combined_wav.read()).decode('utf-8')
            
            # Create the merged audio data object
            merged_data = {
                "mic_audio": merged_mic_audio,
                "desktop_audio": desktop_audio,
                "timestamp": time.time()
            }
            
            return merged_data
        
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error merging audio segments: {e}", flush=True)
            return audio_data_list[-1]  # Return the last one as fallback

    # Function to drain the queue and get all current audio data
    def drain_audio_queue():
        """Get all currently available audio data from the queue"""
        audio_list = []
        
        # Get the first item (we already got it in the main loop)
        first_audio = audio_queue.get()
        audio_list.append(first_audio)
        audio_queue.task_done()
        
        # Drain remaining items from the queue
        try:
            while True:
                # Use get_nowait to avoid blocking
                audio_data = audio_queue.get_nowait()
                audio_list.append(audio_data)
                audio_queue.task_done()
        except queue.Empty:
            # Queue is empty, we've gotten all items
            pass
            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📋 Drained {len(audio_list)} items from audio queue", flush=True)
        return audio_list

    while True:
        try:
            # Check if microphone is enabled and update status if needed
            mic_enabled = True
            if overlay:
                mic_enabled = overlay.mic_button.isChecked()
                if mic_enabled != prev_mic_enabled:
                    if mic_enabled:
                        overlay.update_status("Listening...", "#4CAF50")
                    else:
                        overlay.update_status("Microphone Off", "#FFA500")  # Orange color for disabled state
                    prev_mic_enabled = mic_enabled

            # Wait for audio data
            # We'll wait here until at least one audio item is available
            audio_data = audio_queue.get()
            
            # Skip processing if microphone is disabled
            if not mic_enabled:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🤫 Microphone disabled, skipping audio processing", flush=True)
                audio_queue.task_done()
                continue
            
            sys.stdout.flush()
            
            try:
                # Check if we're currently processing
                if is_processing:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Already processing, putting back in queue and skipping", flush=True)
                    # Put the item back in the queue and continue
                    audio_queue.put(audio_data)
                    continue
                
                # Set processing flag
                is_processing = True
                if overlay:
                    overlay.set_processing(True)
                
                # Drain all current items from the queue including the one we just got
                # Put the first audio back in the queue first
                audio_queue.put(audio_data)
                all_audio_data = drain_audio_queue()
                
                # Filter out duplicates and already processed audio
                filtered_audio = []
                for data in all_audio_data:
                    # Get audio fingerprint
                    fingerprint = get_audio_fingerprint(data)
                    
                    # Skip invalid audio
                    if fingerprint is None:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Invalid audio data skipped", flush=True)
                        continue
                        
                    # Skip already processed audio
                    if fingerprint in processed_hashes:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Duplicate audio fingerprint skipped", flush=True)
                        continue
                    
                    # Add to filtered list and mark as processed
                    filtered_audio.append(data)
                    processed_hashes.add(fingerprint)
                
                # Limit the size of the processed_hashes set to prevent memory growth
                if len(processed_hashes) > 100:
                    processed_hashes = set(list(processed_hashes)[-50:])
                
                # Skip if no valid audio to process
                if not filtered_audio:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ No valid audio to process after filtering", flush=True)
                    is_processing = False
                    if overlay:
                        overlay.set_processing(False)
                    continue
                
                # Capture screenshot
                screenshot_base64 = capture_screenshot()
                
                # Check if we have multiple audio segments to merge
                if len(filtered_audio) > 1:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎙️ Processing {len(filtered_audio)} audio segments together", flush=True)
                    # Reverse the order of audio segments to ensure chronological order (earliest first)
                    filtered_audio.reverse()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Audio segments reversed for chronological order", flush=True)
                    # Merge audio segments
                    merged_audio = merge_audio_data(filtered_audio)
                    processing_audio = merged_audio
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎙️ Processing single audio segment", flush=True)
                    processing_audio = filtered_audio[0]
                
                # Process audio input - this is now asynchronous and will update UI from its thread
                # When the asynchronous call completes, it will set overlay.is_processing to False
                # We don't need to set is_processing to False here anymore
                analyze_with_streaming(processing_audio, screenshot_base64)
                
                # Note: we don't reset the processing state here anymore as it's done in the async thread
                # Instead, we rely on a callback to set is_processing back to False when processing is complete
                # We need to create a way to listen for when the API call is complete
                def check_processing_status():
                    """Check if the overlay is done processing and update our local flag"""
                    nonlocal is_processing
                    # Give time for the thread to start
                    time.sleep(0.5)
                    
                    # Wait until the overlay is no longer processing
                    while overlay and overlay.is_processing:
                        time.sleep(0.5)
                    
                    # Once overlay is done, update our local state
                    is_processing = False
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Processing complete, ready for next input", flush=True)
                
                # Start a thread to monitor when processing is complete
                status_thread = threading.Thread(target=check_processing_status, daemon=True)
                status_thread.start()
            
            except Exception as e:
                print(f"Error processing audio: {e}", flush=True)
                if overlay:
                    overlay.update_status("Error", "#FF0000")
                    overlay.set_processing(False)
                is_processing = False
            
        except Exception as e:
            print(f"Error in process_task: {e}", flush=True)
            is_processing = False
            time.sleep(0.1)  # Prevent tight loop on error

def analyze_with_streaming(audio_data, screenshot_base64):
    """Analyze audio and image and return complete response"""
    global overlay
    
    # Generate a session ID for this analysis
    session_id = f"session_{datetime.now().strftime('%H%M%S')}_{hash(str(audio_data))}"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🆔 Processing session {session_id}", flush=True)
    
    try:
        sys.stdout.flush()
        
        # Extract microphone and desktop audio
        mic_audio = audio_data.get("mic_audio", "")
        
        # Check if desktop audio should be included
        include_desktop_audio = overlay and overlay.desktop_audio_button.isChecked()
        desktop_audio = audio_data.get("desktop_audio", "") if include_desktop_audio else ""
        
        # Collect all queued screenshots, considering the toggle state
        screenshots = []
        if overlay and overlay.screenshot_toggle_button.isChecked():
            from overlay import screenshot_queue
            while not screenshot_queue.empty():
                try:
                    screenshot = screenshot_queue.get_nowait()
                    screenshots.append(screenshot)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Using queued screenshot for analysis", flush=True)
                except queue.Empty:
                    break
            
            # If no queued screenshots, use the current one passed to the function
            if not screenshots:
                screenshots = [screenshot_base64]
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Using current screenshot for analysis", flush=True)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚫 Screenshots disabled, not sending image data", flush=True)
            
        # Update UI to show processing state
        if overlay:
            overlay.update_status("Processing...", "#FFA500")
            
        # Run the API call in a separate thread to avoid blocking the UI
        def api_call_thread():
            try:
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
                    
                    # Start the analysis request with all screenshots
                    response_json = analyze_with_audio_and_image(
                        mic_audio, 
                        "wav", 
                        screenshots, 
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
                    
                    sys.stdout.flush()
                    
                    # Update overlay with structured response from the main thread
                    if overlay:
                        QtCore.QMetaObject.invokeMethod(
                            overlay, 
                            "update_response",
                            QtCore.Qt.ConnectionType.QueuedConnection,
                            QtCore.Q_ARG(dict, response_json)
                        )
                        QtCore.QMetaObject.invokeMethod(
                            overlay,
                            "update_status",
                            QtCore.Qt.ConnectionType.QueuedConnection,
                            QtCore.Q_ARG(str, "Listening..."),
                            QtCore.Q_ARG(str, "#4CAF50")
                        )
                        QtCore.QMetaObject.invokeMethod(
                            overlay,
                            "set_processing",
                            QtCore.Qt.ConnectionType.QueuedConnection,
                            QtCore.Q_ARG(bool, False)
                        )
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error in analysis session {session_id}: {e}", flush=True)
                if overlay:
                    error_response = {"user_query": "Error occurred", "response": f"Error: {str(e)}"}
                    QtCore.QMetaObject.invokeMethod(
                        overlay,
                        "update_status",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(str, "Error"),
                        QtCore.Q_ARG(str, "#FF0000")
                    )
                    QtCore.QMetaObject.invokeMethod(
                        overlay,
                        "update_response",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(dict, error_response)
                    )
                    QtCore.QMetaObject.invokeMethod(
                        overlay,
                        "set_processing",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(bool, False)
                    )
                sys.stdout.flush()
                
        # Start the thread
        thread = threading.Thread(target=api_call_thread)
        thread.daemon = True
        thread.start()
        
        # Return None since the actual response will be handled in the background thread
        return None
    
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error setting up analysis session {session_id}: {e}", flush=True)
        if overlay:
            overlay.update_status("Error", "#FF0000")
            error_response = {"user_query": "Error occurred", "response": f"Error: {str(e)}"}
            overlay.update_response(error_response)
            overlay.set_processing(False)
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
            overlay.update_status("Processing...", "#FFA500")
        
        # Collect screenshots and audio on the main thread before sending to background
        screenshots = []
        if overlay and overlay.screenshot_toggle_button.isChecked():
            from overlay import screenshot_queue
            # Collect all queued screenshots
            while not screenshot_queue.empty():
                try:
                    screenshot = screenshot_queue.get_nowait()
                    screenshots.append(screenshot)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Using queued screenshot for text input", flush=True)
                except queue.Empty:
                    break
            
            # If no queued screenshots, capture a new one
            if not screenshots:
                screenshots = [capture_screenshot()]
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Capturing new screenshot for text input", flush=True)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚫 Screenshots disabled, not sending image data for text input", flush=True)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 💬 Text input received: {text_input}", flush=True)
        
        # Get desktop audio from speech_capture
        from speech_capture import get_desktop_speech_segments
        
        # Check if desktop audio should be included
        include_desktop_audio = overlay and overlay.desktop_audio_button.isChecked()
        desktop_audio = get_desktop_speech_segments() if include_desktop_audio else ""
        
        # Log desktop audio status
        if desktop_audio:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔊 Desktop audio captured and included", flush=True)
        elif not include_desktop_audio:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔇 Desktop audio available but not included (disabled)", flush=True)
        
        # Run the API call in a separate thread to avoid blocking the UI
        def api_call_thread():
            try:
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
                    
                    # Process the text input with all screenshots
                    response_json = analyze_with_text_input(
                        text_input,
                        screenshots,
                        "jpeg",
                        desktop_audio
                    )
                    
                    # Use QtCore.QMetaObject.invokeMethod to safely update UI from background thread
                    if overlay:
                        # Update UI from the main thread
                        QtCore.QMetaObject.invokeMethod(
                            overlay, 
                            "update_response",
                            QtCore.Qt.ConnectionType.QueuedConnection,
                            QtCore.Q_ARG(dict, response_json)
                        )
                        QtCore.QMetaObject.invokeMethod(
                            overlay,
                            "update_status",
                            QtCore.Qt.ConnectionType.QueuedConnection,
                            QtCore.Q_ARG(str, "Listening..."),
                            QtCore.Q_ARG(str, "#4CAF50")
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
                    
                    sys.stdout.flush()
                    
            except Exception as e:
                print(f"Error in background thread: {e}", flush=True)
                if overlay:
                    # Update UI from the main thread
                    QtCore.QMetaObject.invokeMethod(
                        overlay,
                        "update_status",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(str, "Error"),
                        QtCore.Q_ARG(str, "#FF0000")
                    )
                    error_response = {"user_query": text_input, "response": f"Error: {str(e)}"}
                    QtCore.QMetaObject.invokeMethod(
                        overlay,
                        "update_response",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(dict, error_response)
                    )
            finally:
                # Always reset processing state when done
                if overlay:
                    QtCore.QMetaObject.invokeMethod(
                        overlay,
                        "set_processing",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(bool, False)
                    )
        
        # Start the thread
        thread = threading.Thread(target=api_call_thread)
        thread.daemon = True
        thread.start()
        
    except Exception as e:
        print(f"Error setting up text input processing: {e}", flush=True)
        if overlay:
            overlay.update_status("Error", "#FF0000")
            overlay.update_response({"user_query": text_input, "response": f"Error: {str(e)}"})
            overlay.set_processing(False)

def process_pro_text_input(text_input):
    """Process text input from the overlay UI using the Pro model for coding problems"""
    global overlay
    
    try:
        # Check if we're already processing something
        if overlay and overlay.is_processing:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Already processing another request, ignoring text input", flush=True)
            return
        
        # Set processing state
        if overlay:
            overlay.set_processing(True)
            overlay.update_status("Processing with Pro model...", "#4B0082")  # Indigo color for Pro
        
        # Collect screenshots and audio on the main thread before sending to background
        screenshots = []
        if overlay and overlay.screenshot_toggle_button.isChecked():
            from overlay import screenshot_queue
            # Collect all queued screenshots
            while not screenshot_queue.empty():
                try:
                    screenshot = screenshot_queue.get_nowait()
                    screenshots.append(screenshot)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Using queued screenshot for Pro input", flush=True)
                except queue.Empty:
                    break
            
            # If no queued screenshots, capture a new one
            if not screenshots:
                screenshots = [capture_screenshot()]
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Capturing new screenshot for Pro input", flush=True)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚫 Screenshots disabled, not sending image data for Pro input", flush=True)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 💬 Pro analysis request received: {text_input}", flush=True)
        
        # Get desktop audio from speech_capture
        from speech_capture import get_desktop_speech_segments
        
        # Check if desktop audio should be included
        include_desktop_audio = overlay and overlay.desktop_audio_button.isChecked()
        desktop_audio = get_desktop_speech_segments() if include_desktop_audio else ""
        
        # Log desktop audio status
        if desktop_audio:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔊 Desktop audio captured and included", flush=True)
        elif not include_desktop_audio:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔇 Desktop audio available but not included (disabled)", flush=True)
        
        # Run the API call in a separate thread to avoid blocking the UI
        def api_call_thread():
            try:
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
                    
                    # Import the Pro model analysis function
                    from chat import analyze_with_pro_model
                    
                    # Process the text input with all screenshots using the Pro model
                    response_json = analyze_with_pro_model(
                        text_input,
                        screenshots,
                        "jpeg",
                        desktop_audio
                    )
                    
                    # Use QtCore.QMetaObject.invokeMethod to safely update UI from background thread
                    if overlay:
                        # Update UI from the main thread
                        QtCore.QMetaObject.invokeMethod(
                            overlay, 
                            "update_response",
                            QtCore.Qt.ConnectionType.QueuedConnection,
                            QtCore.Q_ARG(dict, response_json)
                        )
                        QtCore.QMetaObject.invokeMethod(
                            overlay,
                            "update_status",
                            QtCore.Qt.ConnectionType.QueuedConnection,
                            QtCore.Q_ARG(str, "Listening..."),
                            QtCore.Q_ARG(str, "#4CAF50")
                        )
                    
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 💬 Pro AI response:", flush=True)
                    print("-" * 50, flush=True)
                    sys.stdout.flush()
                    
                    # Extract the user query and response
                    user_query = response_json.get("user_query", text_input)
                    ai_response = response_json.get("response", "No response generated")
                    
                    # Print the complete response
                    print(f"User's query: {user_query}\n")
                    print(f"AI response: {ai_response}", flush=True)
                    print("\n" + "-" * 50, flush=True)
                    
                    sys.stdout.flush()
                    
            except Exception as e:
                print(f"Error in Pro model background thread: {e}", flush=True)
                if overlay:
                    # Update UI from the main thread
                    QtCore.QMetaObject.invokeMethod(
                        overlay,
                        "update_status",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(str, "Error"),
                        QtCore.Q_ARG(str, "#FF0000")
                    )
                    error_response = {"user_query": text_input, "response": f"Error: {str(e)}"}
                    QtCore.QMetaObject.invokeMethod(
                        overlay,
                        "update_response",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(dict, error_response)
                    )
            finally:
                # Always reset processing state when done
                if overlay:
                    QtCore.QMetaObject.invokeMethod(
                        overlay,
                        "set_processing",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(bool, False)
                    )
        
        # Start the thread
        thread = threading.Thread(target=api_call_thread)
        thread.daemon = True
        thread.start()
        
    except Exception as e:
        print(f"Error setting up Pro model text input processing: {e}", flush=True)
        if overlay:
            overlay.update_status("Error", "#FF0000")
            overlay.update_response({"user_query": text_input, "response": f"Error: {str(e)}"})
            overlay.set_processing(False)

def main():
    # Set the graphics rendering backend to OpenGL ES
    # This might improve performance on some systems, especially with integrated graphics
    # PyQt6 handles this differently or might not need explicit setting
    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseDesktopOpenGL) # Example if needed
    
    # Create Qt application
    app = QtWidgets.QApplication(sys.argv)
    
    # Create and show the overlay
    global overlay
    overlay = DraggableOverlay()
    overlay.show()
    
    # Connect the text_submitted signal to the process_text_input function
    overlay.text_submitted.connect(process_text_input)
    
    # Connect the pro_text_submitted signal to the process_pro_text_input function
    overlay.pro_text_submitted.connect(process_pro_text_input)
    
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
    app.exec()

if __name__ == "__main__":
    main()