import threading
import queue
import time
from datetime import datetime
import pyaudio
import numpy as np
import sounddevice as sd
from gemini_live import AudioStreamer
import base64
import io
import wave

# Audio parameters
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 48000
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
        
        # Create flag to control desktop audio capture
        self.desktop_capture_running = False
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
            self.mic_streamer = AudioStreamer(
                transcription_callback=self.transcription_callback,
                sample_rate=RATE,
                chunk_size=CHUNK,
                source_type="mic"
            )
            
            # Start the mic streamer
            return self.mic_streamer.start()
        return False
        
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
            
            # Start the desktop streamer without creating a mic stream
            # We'll feed it audio directly via add_audio_chunk
            return self.desktop_streamer.start()
        return False
        
    def capture_desktop_audio(self):
        """Capture desktop audio using sounddevice and feed it to the desktop streamer"""
        try:
            # Try to find Stereo Mix device
            stereo_mix_index = None
            devices = sd.query_devices()
            
            for i, device in enumerate(devices):
                if "stereo mix" in device['name'].lower() and device['max_input_channels'] > 0:
                    stereo_mix_index = i
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Found Stereo Mix device: {device['name']} (index {i})")
                    break
                    
            if stereo_mix_index is None:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No Stereo Mix device found, desktop transcription disabled")
                return
                
            # Define callback function for the sounddevice stream
            def audio_callback(indata, frames, time_info, status):
                if status:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Status: {status}")
                
                # Convert stereo to mono if needed by averaging channels
                if indata.shape[1] > 1:
                    mono_data = np.mean(indata, axis=1)
                else:
                    mono_data = indata[:, 0]
                    
                # Scale float32 (-1.0 to 1.0) to int16 values
                int16_data = (mono_data * 32767).astype(np.int16)
                
                # Convert to bytes
                audio_bytes = int16_data.tobytes()
                
                # Add to desktop streamer
                if self.desktop_streamer and self.desktop_streamer.running:
                    self.desktop_streamer.add_audio_chunk(audio_bytes)
            
            # Start capturing audio from Stereo Mix
            with sd.InputStream(
                device=int(stereo_mix_index), 
                channels=min(2, devices[stereo_mix_index]['max_input_channels']),
                samplerate=RATE,
                callback=audio_callback,
                blocksize=CHUNK,
                dtype='float32'
            ):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture started with Stereo Mix")
                while self.desktop_capture_running:
                    time.sleep(0.1)  # Sleep to prevent high CPU usage
                    
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture error: {e}")
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
                    audio_chunk = stream.read(CHUNK)
                    
                    # Convert to mono if stereo
                    if p.get_device_info_by_index(stereo_mix_index).get('maxInputChannels') > 1:
                        audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
                        audio_array = audio_array.reshape(-1, 2)
                        mono_array = np.mean(audio_array, axis=1, dtype=np.int16)
                        audio_chunk = mono_array.tobytes()
                    
                    # Add to desktop streamer
                    if self.desktop_streamer and self.desktop_streamer.running:
                        self.desktop_streamer.add_audio_chunk(audio_chunk)
                    
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
    
    def stop_transcription(self):
        """Stop all transcription services"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping all transcription services", flush=True)
        
        # Stop desktop audio capture
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