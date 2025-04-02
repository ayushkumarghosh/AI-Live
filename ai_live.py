import threading
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

# Queue to hold audio segments for transcription
audio_queue = queue.Queue()

# Initialize chat history
chat_history = ChatHistory()

# Flag to control ongoing analysis
analysis_in_progress = threading.Event()
cancel_current_analysis = threading.Event()

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
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Screenshot captured: {size_kb:.2f} KB")
    
    return base64.b64encode(img_bytes.getvalue()).decode('utf-8')

def recording_worker():
    """Run recording continuously and push audio segments to queue"""
    print("Starting live recording... Speak whenever you want.")
    try:
        # Modify record_speech to accept a queue and run indefinitely
        record_speech(audio_queue)
    except Exception as e:
        print("Error recording", e)

def process_analysis(chat_history, screenshot_base64, transcription):
    """Process image analysis in separate thread so it can be interrupted"""
    try:
        analysis_in_progress.set()
        cancel_current_analysis.clear()
        
        # Analyze with image and transcript
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Analyzing with image...")
        response = analyze_image_with_history(chat_history, screenshot_base64, "jpeg", transcription)
        
        # Process the streaming response
        client = sseclient.SSEClient(response)
        full_response = ""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Response:")
        
        for event in client.events():
            # Check if we should cancel the current analysis
            if cancel_current_analysis.is_set():
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Analysis interrupted for new transcription")
                try:
                    response.close()
                except:
                    pass
                break
                
            if event.data:
                try:
                    # Handle potential '[DONE]' marker
                    if event.data.strip() == '[DONE]':
                        print("\nStream finished.")
                        break
                    chunk = json.loads(event.data)
                    content = None
                    if len(chunk.get('choices', [{}])) > 0:
                        content = chunk.get('choices', [{}])[0].get('delta', {}).get('content')
                    if content:
                        print(content, end='', flush=True)
                        full_response += content
                except json.JSONDecodeError:
                    print(f"\nReceived non-JSON data: {event.data}")
        
        # Only add to chat history if not canceled
        if not cancel_current_analysis.is_set():
            # Add to chat history
            response_obj = {"choices": [{"message": {"content": full_response}}]}
            chat_history.add_entry(transcription, response_obj, screenshot_base64)
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Analysis complete")
    except Exception as e:
        print(f"Error in analysis: {e}")
    finally:
        analysis_in_progress.clear()

def transcription_worker(audio_queue):
    """Worker to transcribe audio segments from the queue"""
    print("Transcription worker started...")
    analysis_thread = None
    
    while True:
        time.sleep(0.1)
        try:
            audio_data = audio_queue.get()  # Wait for audio segment
            if(audio_data != None):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Transcribing audio segment...")
                transcription = transcribe(audio_data, "wav")
                # transcription = transcribe_audio(audio_data, "small.en")
                if "error404" in transcription or transcription == "":
                    print("skipping...")
                elif transcription:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Transcription: {transcription}")
                    
                    # Capture screenshot
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Capturing screenshot...")
                    screenshot_base64 = capture_screenshot()
                    
                    # Check if there's an ongoing analysis
                    if analysis_in_progress.is_set() and analysis_thread and analysis_thread.is_alive():
                        # Signal to cancel the current analysis
                        cancel_current_analysis.set()
                        # Wait briefly for it to clean up
                        time.sleep(0.5)
                    
                    # Start a new analysis thread
                    analysis_thread = threading.Thread(
                        target=process_analysis,
                        args=(chat_history, screenshot_base64, transcription),
                        daemon=True
                    )
                    analysis_thread.start()
                
                audio_queue.task_done()
        except Exception as e:
            print("Error transcribing: ", e)

if __name__ == "__main__":
    
    # Start transcription worker thread
    transcription_thread = threading.Thread(target=transcription_worker, args=(audio_queue,), daemon=True)
    transcription_thread.start()
    
    # Start recording in main thread
    recording_worker()