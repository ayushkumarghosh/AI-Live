import threading
import queue
from datetime import datetime
from speech_capture import record_speech  # First file
from pollinations import transcribe  # Second file
import time
# from test import transcribe_audio

# Queue to hold audio segments for transcription
audio_queue = queue.Queue()

def recording_worker():
    """Run recording continuously and push audio segments to queue"""
    print("Starting live recording... Speak whenever you want.")
    try:
        # Modify record_speech to accept a queue and run indefinitely
        record_speech(audio_queue)
    except Exception as e:
        print("Error recording", e)

def transcription_worker(audio_queue):
    """Worker to transcribe audio segments from the queue"""
    print("Transcription worker started...")
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
                if transcription:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Transcription: {transcription}")
                audio_queue.task_done()
        except Exception as e:
            print("Error transcribing: ", e)

if __name__ == "__main__":
    
    # Start transcription worker thread
    transcription_thread = threading.Thread(target=transcription_worker, args=(audio_queue,), daemon=True)
    transcription_thread.start()
    
    # Start recording in main thread
    recording_worker()