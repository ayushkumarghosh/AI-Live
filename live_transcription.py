import threading
import queue
import time
from datetime import datetime
import pyaudio
import numpy as np
import sounddevice as sd
import soundcard as sc
import soundfile as sf
import warnings
from gemini_live import AudioStreamer
import base64
import io
import wave

# Filter out SoundcardRuntimeWarning about data discontinuity
warnings.filterwarnings("ignore", message="data discontinuity in recording", category=sc.mediafoundation.SoundcardRuntimeWarning)

# Audio parameters
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 48000  # Using 48kHz to match gemini_live.py
CHUNK = 1024

class LiveTranscriptionManager:
    def __init__(self, transcription_callback=None):
        """
        Initialize the transcription manager
        
        Args:
            transcription_callback: Function to call with transcription results (text, source_type)
        """
        self.transcription_callback = transcription_callback
        
        # Create separate streamers for mic and desktop
        self.mic_streamer = None
        self.desktop_streamer = None
        
        # Create flags to control audio capture
        self.mic_capture_running = False
        self.desktop_capture_running = False
        
        # Create audio queues
        self.mic_audio_queue = queue.Queue()
        self.desktop_audio_queue = queue.Queue()
        
    def start_transcription(self):
        """Start both microphone and desktop audio transcription"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting live transcription services", flush=True)
        
        # Start mic transcription
        self.start_mic_transcription()
        
        # Start desktop audio capture and transcription
        self.start_desktop_transcription()
        
        return True
        
    def start_mic_transcription(self):
        """Start microphone transcription"""
        if self.mic_streamer is None:
            # Create mic audio streamer
            self.mic_streamer = AudioStreamer(
                transcription_callback=self.transcription_callback,
                sample_rate=RATE,
                chunk_size=CHUNK,
                source_type="mic"
            )
            
            # Start microphone capture in a separate thread
            self.mic_capture_running = True
            mic_thread = threading.Thread(
                target=self.capture_mic_audio,
                daemon=True
            )
            mic_thread.start()
            
            # Start the mic streamer
            return self.mic_streamer.start()
        return False
        
    def capture_mic_audio(self):
        """Capture microphone audio and feed it to the mic streamer"""
        try:
            # Get the default microphone
            mic = sc.default_microphone()
            
            if mic is None:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No microphone found. Mic transcription disabled.")
                return
                
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Using microphone: {mic.name}")
            
            # Use a slightly larger blocksize to reduce discontinuities
            adjusted_blocksize = CHUNK * 2
            
            # Record in a loop until mic_capture_running is False
            with mic.recorder(samplerate=RATE, channels=1, blocksize=adjusted_blocksize) as recorder:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting microphone recording")
                
                while self.mic_capture_running:
                    try:
                        # Record audio block with try-except to handle discontinuities
                        audio_data = recorder.record(CHUNK)
                        
                        # Handle potential multi-dimensional data
                        if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
                            audio_data = np.mean(audio_data, axis=1)
                        
                        # Make sure it's a flat array
                        audio_data = audio_data.flatten()
                        
                        # Convert to int16 - directly scaling to int16 range
                        int16_data = np.int16(audio_data * 32767)
                        
                        # Convert to raw PCM bytes - this is what Gemini expects
                        audio_bytes = int16_data.tobytes()
                        
                        # Add to mic streamer
                        if self.mic_streamer and self.mic_streamer.running:
                            self.mic_streamer.add_audio_chunk(audio_bytes)
                    except Exception as e:
                        # Skip this block if there's a recording error, but don't terminate the loop
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipped mic audio block due to: {e}")
                
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Microphone audio capture error: {e}")
            
    def start_desktop_transcription(self):
        """Start desktop audio capture and transcription"""
        if self.desktop_streamer is None:
            # Create a desktop audio streamer
            self.desktop_streamer = AudioStreamer(
                transcription_callback=self.transcription_callback,
                sample_rate=RATE,
                chunk_size=CHUNK,
                source_type="desktop"
            )
            
            # Start desktop audio capture in a separate thread
            self.desktop_capture_running = True
            desktop_thread = threading.Thread(
                target=self.capture_desktop_audio,
                daemon=True
            )
            desktop_thread.start()
            
            # Start the desktop streamer
            return self.desktop_streamer.start()
        return False
        
    def capture_desktop_audio(self):
        """Capture desktop audio using soundcard with loopback capability and feed it to the desktop streamer"""
        try:
            # Get all loopback-capable microphones
            loopback_mics = sc.all_microphones(include_loopback=True)
            
            if not loopback_mics:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No loopback microphones found. Falling back to PyAudio.")
                self.try_pyaudio_fallback()
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
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting desktop audio capture with soundcard loopback")
            
            # Use a slightly larger blocksize to reduce discontinuities
            adjusted_blocksize = CHUNK * 2
            
            # Record in a loop until desktop_capture_running is False
            with loop_mic.recorder(samplerate=RATE, channels=1, blocksize=adjusted_blocksize) as recorder:
                first_chunk = True
                
                # Add additional debug information
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting recorder with samplerate={RATE}, channels=1, blocksize={adjusted_blocksize}")
                
                while self.desktop_capture_running:
                    try:
                        # Record audio block with try-except to handle discontinuities
                        audio_data = recorder.record(CHUNK)
                        
                        # Debug info for first chunk only
                        if first_chunk:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] Audio data shape: {audio_data.shape}, dtype: {audio_data.dtype}")
                            first_chunk = False
                        
                        # Handle potential multi-dimensional data
                        if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
                            audio_data = np.mean(audio_data, axis=1)
                        
                        # Make sure it's a flat array
                        audio_data = audio_data.flatten()
                        
                        # Convert to int16 - directly scaling to int16 range
                        int16_data = np.int16(audio_data * 32767)
                        
                        # Convert to raw PCM bytes - this is what Gemini expects (not WAV)
                        audio_bytes = int16_data.tobytes()
                        
                        # Add to desktop streamer - sending raw PCM data
                        if self.desktop_streamer and self.desktop_streamer.running:
                            self.desktop_streamer.add_audio_chunk(audio_bytes)
                    except Exception as e:
                        # Skip this block if there's a recording error, but don't terminate the loop
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipped desktop audio block due to: {e}")
                
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture error with soundcard: {e}")
            self.try_pyaudio_fallback()
            
    def try_pyaudio_fallback(self):
        """Try capturing desktop audio using PyAudio as a fallback"""
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
            
            # Continuous capture loop
            while self.desktop_capture_running:
                try:
                    # Read raw PCM data directly - this is what Gemini expects
                    audio_chunk = stream.read(CHUNK, exception_on_overflow=False)
                    
                    # Convert to mono if stereo
                    if p.get_device_info_by_index(stereo_mix_index).get('maxInputChannels') > 1:
                        audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
                        audio_array = audio_array.reshape(-1, 2)
                        mono_array = np.mean(audio_array, axis=1, dtype=np.int16)
                        audio_chunk = mono_array.tobytes()
                    
                    # Add raw PCM data to desktop streamer - no need for WAV conversion
                    if self.desktop_streamer and self.desktop_streamer.running:
                        self.desktop_streamer.add_audio_chunk(audio_chunk)
                    
                except Exception as e:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Error reading audio: {e}")
                    # No sleep needed here either to improve responsiveness
            
            # Clean up
            stream.stop_stream()
            stream.close()
            p.terminate()
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] PyAudio fallback failed: {e}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture disabled.")
    
    def stop_transcription(self):
        """Stop all transcription services"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping all transcription services", flush=True)
        
        # Stop audio capture
        self.mic_capture_running = False
        self.desktop_capture_running = False
        
        # Stop streamers
        if self.mic_streamer:
            self.mic_streamer.stop()
            
        if self.desktop_streamer:
            self.desktop_streamer.stop()
            
    def cleanup(self):
        """Clean up all resources"""
        self.stop_transcription()
        
        if self.mic_streamer:
            self.mic_streamer.cleanup()
            self.mic_streamer = None
            
        if self.desktop_streamer:
            self.desktop_streamer.cleanup()
            self.desktop_streamer = None 
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Live transcription manager cleaned up", flush=True) 