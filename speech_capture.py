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
MAX_DESKTOP_BUFFER_DURATION = 300  # Max seconds of desktop audio to keep

# Storage for detected speech from desktop audio
desktop_speech_segments = collections.deque(maxlen=10)  # Store up to 10 recent speech segments

# Flag to control the desktop audio capture thread
desktop_capture_running = False

# Manual speech detection states for desktop audio
desktop_speech_state = {
    "is_speech": False,
    "speech_prob": 0.0,
    "silence_duration": 0,
    "speech_duration": 0, 
    "recording": False,
    "frames": [],
    "silence_start": None
}

def detect_speech(audio_float, is_desktop=False):
    """
    Detect speech in audio using a stateful algorithm instead of VAD iterator.
    This is a simplified speech detection algorithm that doesn't rely on the VAD model.
    """
    # Energy-based speech detection
    energy = np.mean(np.abs(audio_float))
    is_speech = energy > 0.01  # Simple threshold-based detection
    
    # Get the appropriate state object
    state = desktop_speech_state if is_desktop else {}
    
    # Create an event similar to what VAD would return
    event = None
    
    # For desktop audio, update the state
    if is_desktop:
        # Update silence/speech duration
        if is_speech:
            desktop_speech_state["silence_duration"] = 0
            desktop_speech_state["speech_duration"] += 1
            
            # If we've seen enough speech frames and weren't already in speech mode
            if desktop_speech_state["speech_duration"] > 3 and not desktop_speech_state["is_speech"]:
                desktop_speech_state["is_speech"] = True
                event = "start"
        else:
            desktop_speech_state["speech_duration"] = 0
            desktop_speech_state["silence_duration"] += 1
            
            # If we've seen enough silence frames and were in speech mode
            if desktop_speech_state["silence_duration"] > 5 and desktop_speech_state["is_speech"]:
                desktop_speech_state["is_speech"] = False
                event = "end"
    
    # Return the detection result
    if event == "start":
        return {"start": True}
    elif event == "end":
        return {"end": True}
    else:
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
    Capture desktop audio using sounddevice with loopback capability.
    Also performs speech detection on desktop audio.
    """
    global desktop_audio_buffer, desktop_capture_running, desktop_speech_segments
    
    try:
        # Try using the Stereo Mix device directly since it's available in your system
        stereo_mix_index = None
        
        # Look for Stereo Mix device
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            if "stereo mix" in device['name'].lower() and device['max_input_channels'] > 0:
                stereo_mix_index = i
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Found Stereo Mix device: {device['name']} (index {i})")
                break
        
        if stereo_mix_index is not None:
            # Initialize buffer for storing audio data
            max_buffer_samples = int(MAX_DESKTOP_BUFFER_DURATION * RATE)
            buffer = np.zeros(max_buffer_samples, dtype=np.int16)
            buffer_position = 0
            
            # Callback function for audio input
            def audio_callback(indata, frames, time_info, status):
                nonlocal buffer_position
                
                if status:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Status: {status}")
                
                # Convert stereo to mono if needed by averaging channels
                if indata.shape[1] > 1:
                    mono_data = np.mean(indata, axis=1)
                else:
                    mono_data = indata[:, 0]
                    
                # Scale float32 (-1.0 to 1.0) to int16 values
                int16_data = (mono_data * 32767).astype(np.int16)
                
                # Detect speech in desktop audio without using the VAD model
                speech_event = detect_speech(mono_data, is_desktop=True)
                
                # Handle desktop speech events
                if speech_event is not None:
                    if 'start' in speech_event:
                        if not desktop_speech_state["recording"]:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔊 Speech detected in desktop audio")
                            desktop_speech_state["recording"] = True
                            desktop_speech_state["silence_start"] = None
                            desktop_speech_state["frames"] = []
                    elif 'end' in speech_event:
                        desktop_speech_state["silence_start"] = time.time()
                
                # Record desktop audio if speech is detected
                if desktop_speech_state["recording"]:
                    desktop_speech_state["frames"].append(int16_data.tobytes())
                
                # Check for silence timeout after desktop speech ends
                if desktop_speech_state["recording"] and desktop_speech_state["silence_start"] is not None:
                    if time.time() - desktop_speech_state["silence_start"] > SILENCE_LIMIT:
                        desktop_speech_state["recording"] = False
                        
                        # Save the desktop speech segment
                        if desktop_speech_state["frames"]:
                            save_desktop_speech_segment(desktop_speech_state["frames"])
                            desktop_speech_state["frames"] = []
                
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
                global desktop_audio_buffer
                desktop_audio_buffer = buffer.copy()  # Store the entire buffer
            
            # Start capturing audio from Stereo Mix
            with sd.InputStream(
                device=int(stereo_mix_index),  # Cast to int to ensure it's not a string/float
                channels=min(2, devices[stereo_mix_index]['max_input_channels']),
                samplerate=RATE,
                callback=audio_callback,
                blocksize=CHUNK,
                dtype='float32'
            ):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture started with Stereo Mix")
                while desktop_capture_running:
                    time.sleep(0.1)  # Sleep to prevent high CPU usage
        else:
            # No Stereo Mix available, try using PyAudio as a fallback
            print(f"[{datetime.now().strftime('%H:%M:%S')}] No Stereo Mix found, trying PyAudio fallback...")
            try_pyaudio_fallback()
    
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture error: {e}")
        try_pyaudio_fallback()

def save_desktop_speech_segment(frames):
    """Save a desktop speech segment to the global list"""
    global desktop_speech_segments
    
    if not frames:
        return
    
    audio_data = b''.join(frames)
    wav_io = io.BytesIO()
    wf = wave.open(wav_io, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)  # 16-bit audio
    wf.setframerate(RATE)
    wf.writeframes(audio_data)
    wf.close()
    wav_io.seek(0)
    base64_audio = base64.b64encode(wav_io.read()).decode('utf-8')
    
    duration = len(frames) * CHUNK / RATE
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 💾 Saved desktop speech segment: {duration:.1f} seconds")
    
    # Add timestamp and audio data
    desktop_speech_segments.append({
        "timestamp": datetime.now().isoformat(),
        "audio": base64_audio,
        "duration": duration
    })

def try_pyaudio_fallback():
    """Try capturing desktop audio using PyAudio as a fallback"""
    global desktop_audio_buffer, desktop_capture_running, desktop_speech_segments
    
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
        
        # Reset the desktop speech state for PyAudio capture
        global desktop_speech_state
        desktop_speech_state = {
            "is_speech": False,
            "speech_prob": 0.0,
            "silence_duration": 0,
            "speech_duration": 0,
            "recording": False,
            "frames": [],
            "silence_start": None
        }
        
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
                
                # Process for speech detection
                audio_array = np.frombuffer(audio_chunk, dtype=np.int16).copy()
                audio_float = audio_array.astype(np.float32) / 32768.0  # Normalize to [-1, 1]
                
                # Detect speech using our custom function
                speech_event = detect_speech(audio_float, is_desktop=True)
                
                # Handle desktop speech events
                if speech_event is not None:
                    if 'start' in speech_event:
                        if not desktop_speech_state["recording"]:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔊 Speech detected in desktop audio")
                            desktop_speech_state["recording"] = True
                            desktop_speech_state["silence_start"] = None
                            desktop_speech_state["frames"] = []
                    elif 'end' in speech_event:
                        desktop_speech_state["silence_start"] = time.time()
                
                # Record desktop audio if speech is detected
                if desktop_speech_state["recording"]:
                    desktop_speech_state["frames"].append(audio_chunk)
                
                # Check for silence timeout after desktop speech ends
                if desktop_speech_state["recording"] and desktop_speech_state["silence_start"] is not None:
                    if time.time() - desktop_speech_state["silence_start"] > SILENCE_LIMIT:
                        desktop_speech_state["recording"] = False
                        
                        # Save the desktop speech segment
                        if desktop_speech_state["frames"]:
                            save_desktop_speech_segment(desktop_speech_state["frames"])
                            desktop_speech_state["frames"] = []
                
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
        desktop_audio_buffer = []

def get_desktop_speech_segments():
    """Get all stored desktop speech segments as a single base64 WAV"""
    global desktop_speech_segments
    
    if not desktop_speech_segments:
        return ""
    
    try:
        # Collect all speech segments
        all_segments = []
        for segment in desktop_speech_segments:
            all_segments.append(base64.b64decode(segment["audio"]))
        
        if not all_segments:
            return ""
        
        # Merge all segments into one WAV file
        combined_wav = io.BytesIO()
        with wave.open(combined_wav, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit audio
            wf.setframerate(RATE)
            
            # Write all segments to the WAV file
            for segment_data in all_segments:
                # Skip the WAV header and just write the audio data
                with wave.open(io.BytesIO(segment_data), 'rb') as segment_wav:
                    wf.writeframes(segment_wav.readframes(segment_wav.getnframes()))
        
        combined_wav.seek(0)
        base64_audio = base64.b64encode(combined_wav.read()).decode('utf-8')
        
        # Log info about segments
        total_duration = sum(segment["duration"] for segment in desktop_speech_segments)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 Sending {len(desktop_speech_segments)} desktop speech segments ({total_duration:.1f}s total)")
        
        # Clear the segments after sending
        desktop_speech_segments.clear()
        
        return base64_audio
        
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error combining desktop speech segments: {e}")
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
        
        # Handle both list of chunks (PyAudio) and numpy array (sounddevice)
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