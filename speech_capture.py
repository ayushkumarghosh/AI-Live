import pyaudio
import numpy as np
import base64
import io
import time
import wave
from pollinations import transcribe
import webrtcvad

# WebRTC VAD requires frame sizes of 10, 20, or 30ms
# For 16000Hz, this means 320, 640, or 960 samples
RATE = 32000  # WebRTC VAD works best with 16kHz
CHUNK = 960  # 30ms at 16kHz
FORMAT = pyaudio.paInt16
CHANNELS = 1
SILENCE_LIMIT = 1

# Create a VAD object
vad = webrtcvad.Vad()
vad.set_mode(2)  # 0: low, 1: medium, 2: high, 3: very high

def record_speech(audio_queue=None):
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    
    print("Listening...")
    frames = []
    recording = False
    silence_start = None
    
    while True:
        try:
            audio_chunk = stream.read(CHUNK)
            # For VAD, we need the raw bytes
            is_speech_detected = vad.is_speech(audio_chunk, RATE)
            
            if recording:
                frames.append(audio_chunk)
                
            if is_speech_detected:
                if not recording:
                    recording = True
                silence_start = None
            elif recording:
                if silence_start is None:
                    silence_start = time.time()
                elif time.time() - silence_start > SILENCE_LIMIT:
                    recording = False
                    # Convert to WAV in memory and encode to base64
                    audio_data = b''.join(frames)
                    wav_io = io.BytesIO()
                    wf = wave.open(wav_io, 'wb')
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(p.get_sample_size(FORMAT))
                    wf.setframerate(RATE)
                    wf.writeframes(audio_data)
                    wf.close()
                    wav_io.seek(0)
                    base64_audio = base64.b64encode(wav_io.read()).decode('utf-8')
                    
                    if audio_queue:
                        audio_queue.put(base64_audio)  # Push to queue for transcription
                    
                    # Reset frames and continue recording
                    frames = []
        except Exception as e:
            print(f"Error recording: {e}")
                
    stream.stop_stream()
    stream.close()
    p.terminate()