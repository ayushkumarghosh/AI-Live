import pyaudio
import numpy as np
import base64
import io
import time
import wave
from silero_vad import VADIterator, load_silero_vad
from datetime import datetime
import sounddevice as sd
import threading
import platform
import collections
import soundcard as sc

# Audio settings
RATE = 16000
CHUNK = 512  # 32ms at 16 kHz
FORMAT = pyaudio.paInt16
CHANNELS = 1
SILENCE_LIMIT = 1  # Still used for additional silence check after 'end'

# Load a single VAD model instance to be shared
model = load_silero_vad()
vad = VADIterator(model, sampling_rate=RATE)

# Global variables to store audio data
desktop_audio_buffer = []
MAX_DESKTOP_BUFFER_DURATION = 600  # Max seconds of desktop audio to keep

# Storage for continuous desktop audio (last 30 seconds)
DESKTOP_CONTINUOUS_BUFFER_DURATION = 120  # Max seconds of continuous desktop audio to keep
desktop_continuous_buffer = collections.deque(maxlen=int(DESKTOP_CONTINUOUS_BUFFER_DURATION * RATE / CHUNK))  # ~30 seconds at 16kHz

# Flag to control the desktop audio capture thread
desktop_capture_running = False

# No longer needed for manual speech detection

def detect_speech(audio_float, is_desktop=False):
    """
    Detect speech in audio using a stateful algorithm instead of VAD iterator.
    This is a simplified speech detection algorithm that doesn't rely on the VAD model.
    Note: For desktop audio, we no longer detect speech segments as we now capture continuously.
    """
    # Only used for microphone audio now
    if is_desktop:
        return None
        
    # Energy-based speech detection for microphone
    energy = np.mean(np.abs(audio_float))
    is_speech = energy > 0.01  # Simple threshold-based detection
    
    # For microphone audio this will be handled by the VAD model
    return None

def record_speech(audio_queue=None):
    p = pyaudio.PyAudio()
    
    # Open microphone stream with PyAudio
    mic_stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    
    # Start desktop audio capture with sounddevice in a separate thread
    global desktop_capture_running
    desktop_capture_running = True
    desktop_thread = threading.Thread(
        target=capture_desktop_audio_with_sounddevice, 
        daemon=True
    )
    desktop_thread.start()
    
    frames = []
    recording = False
    silence_start = None
    sample_index = 0  # Track total samples processed
    
    # For deduplication - keep a set of recent audio hashes
    recent_audio_hashes = set()
    last_speech_time = 0  # Track when we last sent speech
    
    # Reference to overlay for checking mic state (will be set in the loop)
    overlay = None
    
    # Improved audio hashing function
    def get_audio_fingerprint(audio_data):
        if len(audio_data) < 100:
            return hash(audio_data)
        
        # Create a more robust fingerprint by sampling multiple parts of the audio
        if len(audio_data) > 6000:
            # Take samples from beginning, middle and end for better fingerprinting
            fingerprint = hash(audio_data[:2000] + 
                              audio_data[len(audio_data)//2-1000:len(audio_data)//2+1000] + 
                              audio_data[-2000:])
        else:
            fingerprint = hash(audio_data)
        
        return fingerprint
    
    # Function to check if mic is enabled
    def is_mic_enabled():
        nonlocal overlay
        # Try to get overlay reference if we don't have it yet
        if overlay is None:
            try:
                import sys
                # Look through all modules to find the one with overlay
                for module_name in list(sys.modules.keys()):
                    module = sys.modules[module_name]
                    if hasattr(module, 'overlay') and module.overlay is not None:
                        overlay = module.overlay
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Found overlay reference in {module_name}", flush=True)
                        break
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error finding overlay: {e}", flush=True)
        
        # Check mic state
        if overlay is not None and hasattr(overlay, 'mic_button'):
            return overlay.mic_button.isChecked()
        return True  # Default to enabled if we can't find the reference
    
    while True:
        try:
            # Get current mic state
            mic_enabled = is_mic_enabled()
            
            # Always read the audio to prevent buffer overflow
            audio_chunk = mic_stream.read(CHUNK, exception_on_overflow=False)
            
            # Skip all processing if mic is disabled
            if not mic_enabled:
                # Reset state if microphone is disabled
                if recording or frames:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🤫 Microphone disabled, clearing buffer", flush=True)
                    recording = False
                    frames = []
                    silence_start = None
                # Continue to next iteration without processing
                continue
            
            # Only process audio if mic is enabled
            audio_array = np.frombuffer(audio_chunk, dtype=np.int16).copy()
            audio_array = audio_array.astype(np.float32) / 32768.0  # Normalize to [-1, 1]
            
            # We still use the VAD model for microphone input for better quality
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
                # Perform one final mic check before processing completed audio
                if not is_mic_enabled():
                    # Mic was disabled during silence period, discard audio
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🤫 Microphone disabled during processing, discarding audio", flush=True)
                    recording = False
                    frames = []
                    silence_start = None
                    continue
                    
                recording = False
                audio_data = b''.join(frames)
                
                # Force at least 1 second between speech segments to reduce rapid-fire issues
                current_time = time.time()
                if current_time - last_speech_time < 0.8 and frames:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Too soon after last speech, waiting...", flush=True)
                    frames = []
                    silence_start = None
                    continue
                
                # Create a robust fingerprint of the audio data
                current_audio_fingerprint = get_audio_fingerprint(audio_data)
                
                # Only process if this is not a duplicate of recent audios
                if current_audio_fingerprint not in recent_audio_hashes:
                    # Add to recent hashes
                    recent_audio_hashes.add(current_audio_fingerprint)
                    
                    # Limit set size to prevent memory growth
                    if len(recent_audio_hashes) > 20:
                        # Convert to list, keep most recent 10
                        recent_list = list(recent_audio_hashes)
                        recent_audio_hashes = set(recent_list[-10:])
                    
                    # Track last speech time
                    last_speech_time = current_time
                    
                    # Process the audio
                    wav_io = io.BytesIO()
                    wf = wave.open(wav_io, 'wb')
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(p.get_sample_size(FORMAT))
                    wf.setframerate(RATE)
                    wf.writeframes(audio_data)
                    wf.close()
                    wav_io.seek(0)
                    base64_audio = base64.b64encode(wav_io.read()).decode('utf-8')
                    
                    # Get the desktop audio speech segments
                    desktop_base64_audio = get_desktop_speech_segments()
                    
                    if audio_queue:
                        # Send both microphone and desktop audio
                        audio_queue.put({
                            "mic_audio": base64_audio,
                            "desktop_audio": desktop_base64_audio,
                            "timestamp": time.time(),
                            "fingerprint": current_audio_fingerprint
                        })
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Audio processed and sent to queue (len: {len(audio_data)})", flush=True)
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Duplicate audio detected and skipped", flush=True)
                
                frames = []
                silence_start = None
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error reading audio: {e}", flush=True)
            time.sleep(0.1)  # Sleep on error to prevent CPU spike
    
    # Clean up
    desktop_capture_running = False
    mic_stream.stop_stream()
    mic_stream.close()
    p.terminate()

def capture_desktop_audio_with_sounddevice():
    """
    Capture desktop audio using soundcard with loopback capability.
    This approach is more reliable than searching for Stereo Mix.
    """
    global desktop_audio_buffer, desktop_capture_running, desktop_continuous_buffer
    
    try:
        # Get all loopback-capable microphones
        loopback_mics = sc.all_microphones(include_loopback=True)
        
        if not loopback_mics:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] No loopback microphones found. Falling back to PyAudio.")
            try_pyaudio_fallback()
            return
            
        # Find the loopback mic for the default speaker
        default_spk = sc.default_speaker()
        loop_mic = next(
            (m for m in loopback_mics if default_spk.name in m.name),
            None
        )
        
        # If no associated loopback mic found, fall back to the first one
        if loop_mic is None:
            loop_mic = loopback_mics[0]
            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Using loopback mic: {loop_mic.name}")
        
        # Initialize buffer for storing audio data
        max_buffer_samples = int(MAX_DESKTOP_BUFFER_DURATION * RATE)
        buffer = np.zeros(max_buffer_samples, dtype=np.int16)
        buffer_position = 0
        
        # Initialize desktop_audio_buffer as numpy array if it's not already
        global desktop_audio_buffer
        if isinstance(desktop_audio_buffer, list):
            desktop_audio_buffer = np.zeros(max_buffer_samples, dtype=np.int16)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting desktop audio capture with soundcard loopback")
        
        # Record in a loop until desktop_capture_running is False
        with loop_mic.recorder(samplerate=RATE, channels=1, blocksize=CHUNK) as recorder:
            while desktop_capture_running:
                # Record audio block
                audio_data = recorder.record(CHUNK)
                
                # Convert to int16
                int16_data = (audio_data * 32767).astype(np.int16)
                
                # Calculate how many samples can fit in the remaining buffer
                samples_to_copy = min(len(int16_data), max_buffer_samples - buffer_position)
                
                if samples_to_copy > 0:
                    # Copy to buffer
                    buffer[buffer_position:buffer_position + samples_to_copy] = int16_data[:samples_to_copy]
                    buffer_position += samples_to_copy
                
                # If buffer is full, wrap around to beginning
                if buffer_position >= max_buffer_samples:
                    buffer_position = 0
                
                # Store the audio in the global buffer
                desktop_audio_buffer = buffer.copy()  # Store the entire buffer
                
                # Add to continuous buffer
                desktop_continuous_buffer.append(int16_data.tobytes())
                
                # Sleep briefly to prevent high CPU usage
                time.sleep(0.001)
                
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture error with soundcard: {e}")
        try_pyaudio_fallback()

# Function no longer needed as we don't save speech segments

def try_pyaudio_fallback():
    """Try capturing desktop audio using PyAudio as a fallback"""
    global desktop_audio_buffer, desktop_capture_running, desktop_continuous_buffer
    
    try:
        p = pyaudio.PyAudio()
        
        # List all audio devices
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Searching for input devices with PyAudio...")
        stereo_mix_index = None
        
        for i in range(p.get_device_count()):
            device_info = p.get_device_info_by_index(i)
            device_name = device_info.get('name', '').lower()
            inputs = device_info.get('maxInputChannels', 0)
            
            print(f"PyAudio Device {i}: {device_name} (inputs: {inputs})")
            
            if inputs > 0 and ('stereo mix' in device_name or 'what u hear' in device_name):
                stereo_mix_index = i
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Found PyAudio Stereo Mix: {device_info.get('name')}")
                break
        
        if stereo_mix_index is None:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] No suitable recording device found. Desktop audio capture disabled.")
            desktop_audio_buffer = [] if isinstance(desktop_audio_buffer, list) else np.array([])
            return
        
        # Open Stereo Mix stream
        stream = p.open(
            format=FORMAT,
            channels=min(2, p.get_device_info_by_index(stereo_mix_index).get('maxInputChannels')),
            rate=RATE,
            input=True,
            input_device_index=stereo_mix_index,
            frames_per_buffer=CHUNK
        )
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture started with PyAudio")
        
        # Initialize buffer
        max_frames = int(MAX_DESKTOP_BUFFER_DURATION * RATE / CHUNK)
        desktop_audio_buffer = []
        
        # Continuous capture loop
        while desktop_capture_running:
            try:
                audio_chunk = stream.read(CHUNK)
                
                # Convert to mono if stereo
                if p.get_device_info_by_index(stereo_mix_index).get('maxInputChannels') > 1:
                    audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
                    audio_array = audio_array.reshape(-1, 2)
                    mono_array = np.mean(audio_array, axis=1, dtype=np.int16)
                    audio_chunk = mono_array.tobytes()
                
                # Add to global buffer
                desktop_audio_buffer.append(audio_chunk)
                
                # Keep buffer size within limits
                if len(desktop_audio_buffer) > max_frames:
                    desktop_audio_buffer = desktop_audio_buffer[-max_frames:]
                    
                # Add to continuous buffer (always keeps the last 30 seconds)
                desktop_continuous_buffer.append(audio_chunk)
                
                # Avoid high CPU usage
                time.sleep(0.001)
                
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error reading audio: {e}")
                time.sleep(0.1)
        
        # Clean up
        stream.stop_stream()
        stream.close()
        p.terminate()
        
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] PyAudio fallback failed: {e}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture disabled.")
        desktop_audio_buffer = [] if isinstance(desktop_audio_buffer, list) else np.array([])

def get_desktop_speech_segments():
    """Get the last 30 seconds of continuous desktop audio as a single base64 WAV"""
    global desktop_continuous_buffer
    
    if not desktop_continuous_buffer:
        return ""
    
    try:
        # Combine all audio chunks in the continuous buffer
        audio_data = b''.join(desktop_continuous_buffer)
        
        if not audio_data:
            return ""
        
        # Create a WAV file from the continuous buffer
        combined_wav = io.BytesIO()
        with wave.open(combined_wav, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit audio
            wf.setframerate(RATE)
            wf.writeframes(audio_data)
        
        combined_wav.seek(0)
        base64_audio = base64.b64encode(combined_wav.read()).decode('utf-8')
        
        # Log info about the continuous buffer
        buffer_duration = len(desktop_continuous_buffer) * CHUNK / RATE
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 Sending {buffer_duration:.1f}s of continuous desktop audio")
        
        # Clear the buffer after sending
        desktop_continuous_buffer.clear()
        
        return base64_audio
        
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error processing continuous desktop audio: {e}")
        return ""

def get_desktop_audio_buffer(p):
    """Convert current desktop audio buffer to base64 encoded WAV"""
    global desktop_audio_buffer
    
    if isinstance(desktop_audio_buffer, list) and len(desktop_audio_buffer) == 0:
        return ""
    
    if isinstance(desktop_audio_buffer, np.ndarray) and desktop_audio_buffer.size == 0:
        return ""
    
    try:
        # Create a WAV file in memory
        wav_io = io.BytesIO()
        wf = wave.open(wav_io, 'wb')
        wf.setnchannels(CHANNELS)  # Always save as mono
        wf.setsampwidth(2)  # 16-bit audio (int16)
        wf.setframerate(RATE)
        
        # Handle both list of chunks (PyAudio) and numpy array (soundcard)
        if isinstance(desktop_audio_buffer, list):
            audio_data = b''.join(desktop_audio_buffer)
            wf.writeframes(audio_data)
        else:
            wf.writeframes(desktop_audio_buffer.tobytes())
            
        wf.close()
        wav_io.seek(0)
        
        # Encode to base64
        base64_audio = base64.b64encode(wav_io.read()).decode('utf-8')
        
        # Get duration for logging
        if isinstance(desktop_audio_buffer, list):
            duration = len(desktop_audio_buffer) * CHUNK / RATE
        else:
            duration = len(desktop_audio_buffer) / RATE
            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio captured: {duration:.1f} seconds")
        return base64_audio
        
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error converting desktop audio: {e}")
        return ""

# if __name__ == "__main__":
#     record_speech()