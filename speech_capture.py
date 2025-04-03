import pyaudio
import numpy as np
import base64
import io
import time
import wave
from silero_vad import VADIterator, load_silero_vad
from datetime import datetime

# Audio settings
RATE = 16000
CHUNK = 512  # 32ms at 16 kHz
FORMAT = pyaudio.paInt16
CHANNELS = 1
SILENCE_LIMIT = 1  # Still used for additional silence check after 'end'

# Load the Silero VAD model and initialize VADIterator
model = load_silero_vad()
vad = VADIterator(model, sampling_rate=RATE)

def record_speech(audio_queue=None):
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    
    frames = []
    recording = False
    silence_start = None
    sample_index = 0  # Track total samples processed
    
    while True:
        audio_chunk = stream.read(CHUNK)
        audio_array = np.frombuffer(audio_chunk, dtype=np.int16).copy()
        audio_array = audio_array.astype(np.float32) / 32768.0  # Normalize to [-1, 1]
        
        # Process chunk with VADIterator
        speech_event = vad(audio_array)
        
        # Update sample index
        sample_index += CHUNK
        
        # Handle speech events
        if speech_event is not None:
            if 'start' in speech_event:
                recording = True
                silence_start = None
            elif 'end' in speech_event:
                silence_start = time.time()  # Start silence timer after speech ends
        
        # Append audio if recording
        if recording:
            frames.append(audio_chunk)
        
        # Check for silence timeout after speech ends
        if not recording and silence_start is None and frames:
            silence_start = time.time()
        elif silence_start is not None and time.time() - silence_start > SILENCE_LIMIT and frames:
            recording = False
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
                audio_queue.put(base64_audio)
            frames = []
            silence_start = None
    
    stream.stop_stream()
    stream.close()
    p.terminate()

# if __name__ == "__main__":
#     record_speech()