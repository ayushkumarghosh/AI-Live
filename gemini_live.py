import asyncio
from pathlib import Path
from google import genai
from google.genai import types
import os 
import pyaudio
import time
import queue
import threading
from datetime import datetime

api_key = os.getenv("GEMINI_API")

# Audio parameters
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 48000  # Changed to match speech_capture.py
CHUNK = 1024   # Changed to match speech_capture.py

class AudioStreamer:
    def __init__(self, transcription_callback=None, sample_rate=RATE, chunk_size=CHUNK, source_type="mic"):
        """
        Initialize the AudioStreamer with optional callback function
        
        Args:
            transcription_callback: Function to call when transcription is received
            sample_rate: Audio sample rate (default 48000 Hz)
            chunk_size: Audio chunk size (default 1024 samples)
            source_type: Type of audio source ('mic' or 'desktop')
        """
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.audio_queue = None
        self.transcription_callback = transcription_callback
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.running = False
        self.loop = None
        self.session = None
        self.tasks = []
        self.source_type = source_type
        
        # Initialize genai client
        if api_key:
            self.client = genai.Client(api_key=api_key)
            self.model = "gemini-2.0-flash-live-001"
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ GEMINI_API environment variable not set", flush=True)
            self.client = None
            
        self.config = {
            "system_instruction": "You are an expert at transcribing and transliterating user's speech to english. If the user is speaking in a different language, you should transliterate it to english. If the user is speaking in english, you should transcribe it to english.",
            "response_modalities": ["TEXT"],
            "context_window_compression": (
                types.ContextWindowCompressionConfig(
                    sliding_window=types.SlidingWindow(),
                )
            ),
        }
        
    async def start_mic_stream(self, device_index=None):
        """Initialize and start the microphone stream"""
        # Open microphone stream - we'll support both passing a stream or creating one
        if self.stream is None:
            self.stream = self.p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size
            )
            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎤 {self.source_type.capitalize()} stream connected to Gemini", flush=True)
        
    async def capture_audio(self, external_stream=None):
        """Continuously capture audio from microphone and put into queue"""
        stream_to_use = external_stream if external_stream else self.stream
        
        while self.running:
            try:
                # Read audio chunk from microphone
                data = await asyncio.to_thread(
                    stream_to_use.read, 
                    self.chunk_size, 
                    exception_on_overflow=False
                )
                
                # Put audio data in queue
                if self.audio_queue:
                    await self.audio_queue.put(data)
                
                # Small delay to prevent overwhelming the queue
                await asyncio.sleep(0.01)
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error capturing {self.source_type} audio: {e}", flush=True)
                await asyncio.sleep(0.1)
            
    async def send_audio_to_gemini(self):
        """Send audio data from queue to Gemini"""
        while self.running:
            try:
                # Get audio chunk from queue
                audio_chunk = await self.audio_queue.get()
                
                # Send to Gemini
                if self.session:
                    await self.session.send_realtime_input(
                        audio=types.Blob(data=audio_chunk, mime_type=f'audio/pcm;rate={self.sample_rate}')
                    )
                
                # Mark task as done
                self.audio_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error sending {self.source_type} audio to Gemini: {e}", flush=True)
                await asyncio.sleep(0.1)
            
    async def process_responses(self):
        """Process responses from Gemini"""
        while self.running:
            try:
                transcription = ""
                if self.session:
                    async for msg in self.session.receive():
                        if msg.text:
                            transcription += msg.text
                            
                # Call the callback if provided
                if self.transcription_callback and transcription.strip():
                    # Call in the event loop to avoid blocking
                    self.transcription_callback(transcription, self.source_type)
                                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error processing {self.source_type} Gemini response: {e}", flush=True)
                await asyncio.sleep(0.1)
    
    def add_audio_chunk(self, audio_chunk):
        """Add audio chunk to the queue (can be called from any thread)"""
        if self.loop and self.running and self.audio_queue:
            asyncio.run_coroutine_threadsafe(self.audio_queue.put(audio_chunk), self.loop)
    
    async def run(self, external_stream=None):
        """Run the transcriber with Gemini"""
        if not self.client:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Cannot start Gemini without API key", flush=True)
            return
            
        try:
            # Create a new queue
            self.audio_queue = asyncio.Queue(maxsize=100)
            
            # Connect to Gemini using async with instead of await
            async with self.client.aio.live.connect(model=self.model, config=self.config) as session:
                self.session = session
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Gemini {self.source_type} transcription session started", flush=True)
                
                # Start microphone stream if needed
                if not external_stream and not self.stream:
                    await self.start_mic_stream()
                
                # Create tasks
                capture_task = asyncio.create_task(self.capture_audio(external_stream))
                send_task = asyncio.create_task(self.send_audio_to_gemini())
                process_task = asyncio.create_task(self.process_responses())
                
                self.tasks = [capture_task, send_task, process_task]
                
                # Wait for tasks
                await asyncio.gather(*self.tasks)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error in {self.source_type} Gemini transcriber: {e}", flush=True)
        finally:
            if self.session:
                # No need to close the session since it's managed by the async with
                self.session = None
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.source_type.capitalize()} Gemini session closed", flush=True)
    
    def start(self, external_stream=None):
        """Start the transcriber in a background thread"""
        if not api_key:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Cannot start Gemini without API key. Set GEMINI_API environment variable.", flush=True)
            return False
            
        def run_async_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.running = True
            self.loop.run_until_complete(self.run(external_stream))
            
        thread = threading.Thread(target=run_async_loop, daemon=True)
        thread.start()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Gemini {self.source_type} transcriber started", flush=True)
        return True
    
    def stop(self):
        """Stop the transcriber"""
        self.running = False
        if self.loop:
            for task in self.tasks:
                if not task.done():
                    # Cancel the task directly, task.cancel() returns a boolean, not a coroutine
                    task.cancel()
            
            # Since we're using async with for session management, 
            # we don't need to explicitly close it
            self.session = None
                
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.source_type.capitalize()} Gemini transcriber stopped", flush=True)
    
    def cleanup(self):
        """Clean up resources"""
        self.stop()
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.p.terminate()

async def main():
    # This function serves as a standalone example when running this file directly
    audio_streamer = AudioStreamer(
        transcription_callback=lambda text, source_type: print(f"Callback received from {source_type}: {text}")
    )
    
    try:
        await audio_streamer.start_mic_stream()
        await audio_streamer.run()
    
    except KeyboardInterrupt:
        print("\nStopping microphone stream...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        audio_streamer.cleanup()

if __name__ == "__main__":
    asyncio.run(main())