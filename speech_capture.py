import pyaudio
import numpy as np
import base64
import io
import time
import wave
from pydub import AudioSegment

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
SILENCE_LIMIT = 1.5
CALIBRATION_DURATION = 5  # Seconds to calibrate noise level
threshold = 500
p = pyaudio.PyAudio()

def calibrate_threshold(duration=CALIBRATION_DURATION):    
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    print("Calibrating background noise... Please remain silent.")
    noise_levels = []
    start_time = time.time()
    
    while time.time() - start_time < duration:
        data = np.frombuffer(stream.read(CHUNK), dtype=np.int16)
        noise_levels.append(np.max(np.abs(data)))
    
    avg_noise = np.mean(noise_levels)
    threshold = max(avg_noise * 3, 500)
    stream.stop_stream()
    stream.close()
    print(f"Calibration complete. Noise level: {avg_noise:.0f}, Threshold set to: {threshold:.0f}")
    return threshold  # Return threshold for external use

def is_speech(data, threshold):
    return np.max(np.abs(data)) > threshold

def record_speech(threshold=threshold, audio_queue=None):
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    frames = []
    recording = False
    silence_start = None
    
    while True:
        time.sleep(0.1)
        data = np.frombuffer(stream.read(CHUNK), dtype=np.int16)
        if is_speech(data, threshold):            
            if not recording:
                recording = True
                frames = []  # Reset frames for new speech segment
            frames.append(data.tobytes())
            silence_start = None
        elif recording:
            if silence_start is None:
                silence_start = time.time()
            elif time.time() - silence_start > SILENCE_LIMIT:
                recording = False
                # Process the recorded audio
                audio_data = b''.join(frames)
                wav_io = io.BytesIO()
                wf = wave.open(wav_io, 'wb')
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(p.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(audio_data)
                wf.close()
                wav_io.seek(0)
                
                audio = AudioSegment.from_wav(wav_io)
                mp3_io = io.BytesIO()
                audio.export(mp3_io, format="mp3", bitrate="32k")
                mp3_io.seek(0)
                
                base64_audio = base64.b64encode(mp3_io.read()).decode('utf-8')
                
                if audio_queue:
                    audio_queue.put(base64_audio)  # Push to queue for transcription
                
                # Reset frames and continue recording
                frames = []
    
    # Cleanup (unreachable, but included for completeness)
    stream.stop_stream()
    stream.close()
    p.terminate()

if __name__ == "__main__":
    threshold = calibrate_threshold()
    record_speech(threshold)