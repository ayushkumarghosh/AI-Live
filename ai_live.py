import threading
import queue
from datetime import datetime
from speech_capture import calibrate_threshold, record_speech  # First file
from pollinations import transcribe  # Second file

# Queue to hold audio segments for transcription
audio_queue = queue.Queue()

def recording_worker(threshold):
    """Run recording continuously and push audio segments to queue"""
    print("Starting live recording... Speak whenever you want.")
    
    # Modify record_speech to accept a queue and run indefinitely
    record_speech(threshold, audio_queue)

def transcription_worker(audio_queue):
    """Worker to transcribe audio segments from the queue"""
    print("Transcription worker started...")
    try:
        while True:
            audio_base64 = audio_queue.get()  # Wait for audio segment
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Transcribing audio segment...")
            transcription = transcribe(audio_base64, "mp3")
            if transcription:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Transcription: {transcription}")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Transcription failed")
            audio_queue.task_done()
    except Exception as e:
        print("Error transcribing: ", e)

if __name__ == "__main__":
    # Calibrate noise threshold using imported function
    threshold = calibrate_threshold()
    
    # Start transcription worker thread
    transcription_thread = threading.Thread(target=transcription_worker, args=(audio_queue,), daemon=True)
    transcription_thread.start()
    
    # Start recording in main thread
    recording_worker(threshold)