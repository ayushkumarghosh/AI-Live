import pyaudio
import numpy as np
import base64
import io
# from pollinations import transcribe_audio
import time
import wave
from pollinations import transcribe

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
SILENCE_LIMIT = 1
CALIBRATION_DURATION = 2  # Seconds to calibrate noise level

def calibrate_threshold(stream, duration=CALIBRATION_DURATION):
    print("Calibrating background noise... Please remain silent.")
    noise_levels = []
    start_time = time.time()
    
    while time.time() - start_time < duration:
        data = np.frombuffer(stream.read(CHUNK), dtype=np.int16)
        noise_levels.append(np.max(np.abs(data)))
    
    # Set threshold as 2x the average noise level, with a minimum of 500
    avg_noise = np.mean(noise_levels)
    threshold = max(avg_noise * 4, 500)
    print(f"Calibration complete. Noise level: {avg_noise:.0f}, Threshold set to: {threshold:.0f}")
    return threshold

def is_speech(data, threshold):
    return np.max(np.abs(data)) > threshold

# def process_audio(base64_audio, audio_format):
#     transcript = transcribe_audio(base64_audio, audio_format)
#     print(transcript)

def record_speech(audio_queue=None):
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    
    # Calibrate threshold
    THRESHOLD = calibrate_threshold(stream)
    
    print("Listening...")
    frames = []
    recording = False
    silence_start = None
    
    while True:
        data = np.frombuffer(stream.read(CHUNK), dtype=np.int16)
        if is_speech(data, THRESHOLD):
            if not recording:
                recording = True
            frames.append(data.tobytes())
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
                
    stream.stop_stream()
    stream.close()
    p.terminate()
    # base64_audio = base64.b64encode(wav_io.read()).decode('utf-8')
    
    # Also save to a file on disk
    # timestamp = time.strftime("%Y%m%d-%H%M%S")
    # output_filename = f"speech_recording_{timestamp}.wav"
    # with wave.open(output_filename, 'wb') as wf_file:
    #     wf_file.setnchannels(CHANNELS)
    #     wf_file.setsampwidth(p.get_sample_size(FORMAT))
    #     wf_file.setframerate(RATE)
    #     wf_file.writeframes(audio_data)
    # print(f"Audio saved to {output_filename}")
    
    # Pass to processing function
    # process_audio(base64_audio, "wav")

# if __name__ == "__main__":
#     record_speech()