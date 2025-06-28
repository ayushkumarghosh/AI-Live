import asyncio
from pathlib import Path
from google import genai
from google.genai import types
import os 
import time
import queue
import threading
from datetime import datetime
import soundcard as sc
import numpy as np

api_key = os.getenv("GEMINI_API")

# Audio parameters (no longer using pyaudio constants)
SAMPLE_RATE = 48000
CHANNELS = 1
CHUNK_SIZE = 1024

class AudioStreamer:
    def __init__(self, transcription_callback=None, sample_rate=SAMPLE_RATE, chunk_size=CHUNK_SIZE, source_type="mic", session_handle=None):
        """
        Initialize the AudioStreamer with optional callback function
        
        Args:
            transcription_callback: Function to call when transcription is received
            sample_rate: Audio sample rate (default 48000 Hz)
            chunk_size: Audio chunk size (default 1024 samples)
            source_type: Type of audio source ('mic' or 'desktop')
            session_handle: Optional handle to resume a previous session
        """
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
        self.session_handle = session_handle
        self._should_reconnect = False
        self._pending_session_handle = None
        self._error_retries = 0
        
        # Initialize genai client
        if api_key:
            self.client = genai.Client(api_key=api_key)
            self.model = "gemini-live-2.5-flash-preview"
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ GEMINI_API environment variable not set", flush=True)
            self.client = None
            
    async def capture_audio(self, external_stream=None):
        """Continuously capture audio from external source and put into queue"""
        if external_stream:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Using external audio stream", flush=True)
            while self.running:
                try:
                    # Read from external stream
                    data = await asyncio.to_thread(
                        external_stream.read, 
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
        else:
            # When no external stream is provided, we expect audio to be fed via add_audio_chunk
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for audio to be fed via add_audio_chunk", flush=True)
            while self.running:
                # Just keep the task running to allow processing audio added via add_audio_chunk
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
                        # Check for session resumption update
                        if msg.session_resumption_update:
                            update = msg.session_resumption_update
                            if update.resumable and update.new_handle:
                                # Store pending new handle until go_away
                                self._pending_session_handle = update.new_handle
                        # Only reconnect when we get a go_away signal
                        if msg.go_away is not None:
                            # Connection will soon be terminated; resume with pending handle
                            if self._pending_session_handle:
                                self.session_handle = self._pending_session_handle
                                self._pending_session_handle = None
                            self._should_reconnect = True
                            # Cancel other tasks to reconnect
                            for t in self.tasks:
                                if t is not asyncio.current_task():
                                    t.cancel()
                            return
                        # Process text transcription
                        if msg.text:
                            transcription += msg.text
                # Call the callback if provided
                if self.transcription_callback and transcription.strip():
                    # With JSON response format, we need to parse the transcription
                    try:
                        import json
                        import re
                        
                        # Clean up the transcription text to extract just the JSON part
                        # Remove markdown code block markers if present
                        cleaned_text = transcription
                        
                        # Pattern to match JSON code blocks: ```json {...} ``` or just ```{...}```
                        json_pattern = r'```(?:json)?\s*({.*?})\s*```'
                        json_match = re.search(json_pattern, cleaned_text, re.DOTALL)
                        
                        if json_match:
                            # Extract just the JSON content from the code block
                            cleaned_text = json_match.group(1)
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Extracted JSON from code block", flush=True)
                        
                        # Attempt to parse the JSON
                        response_data = json.loads(cleaned_text)
                        
                        # Debug the successful parse
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Successfully parsed JSON response", flush=True)
                        
                        # Pass the full response_data to the callback
                        # Call in the event loop to avoid blocking
                        self.transcription_callback(response_data, self.source_type)
                    except json.JSONDecodeError as e:
                        # Fallback to raw text if not valid JSON
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Invalid JSON response: {e}", flush=True)
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Raw text: {transcription[:100]}...", flush=True)
                        # Create a simple dict with just the transcription
                        fallback_data = {"transcription": transcription}
                        self.transcription_callback(fallback_data, self.source_type)
                                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error processing {self.source_type} Gemini response: {e}", flush=True)
                await asyncio.sleep(0.1)
                # Attempt to reconnect on error, up to 3 retries
                self._error_retries += 1
                if self._error_retries <= 3:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Retrying {self.source_type} session (attempt {self._error_retries}/3)...", flush=True)
                    self._should_reconnect = True
                    for t in self.tasks:
                        if t is not asyncio.current_task():
                            t.cancel()
                    return
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Max retry attempts reached, stopping {self.source_type} session.", flush=True)
                    self.running = False
                    return
    
    def add_audio_chunk(self, audio_chunk):
        """Add audio chunk to the queue (can be called from any thread)"""
        if self.loop and self.running and self.audio_queue:
            asyncio.run_coroutine_threadsafe(self.audio_queue.put(audio_chunk), self.loop)
    
    async def run(self, external_stream=None):
        """Run the transcriber with Gemini, with automatic session resumption."""
        if not self.client:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Cannot start Gemini without API key", flush=True)
            return

        # Create a new queue for audio data
        self.audio_queue = asyncio.Queue(maxsize=100)
        # Loop to handle initial and resumed sessions
        while self.running:
            # Build config for live connection
            # Create different system instructions based on source type
            if self.source_type == "desktop":
                system_instruction = """
                You are an expert at transcribing and transliterating speech to English.
                
                Always respond with valid JSON in this format:
                {
                  "transcription": "the transcribed text from the audio",
                  "interviewer_answer": "a suggested answer to the interviewer's question as a software engineer"
                }
                
                For the interviewer_answer field, provide a suitable response that a software engineer might give to the question.
                If you're not sure about an answer, provide a plausible response that would be appropriate.
                Both fields are required in every response.
                """
            else:
                system_instruction = """
                You are an expert at transcribing and transliterating user's speech to English.
                If the user is speaking in a different language, transliterate it to English.
                If the user is speaking in English, transcribe it accurately.
                
                Always respond with valid JSON in this format:
                {
                  "transcription": "the transcribed text from the audio"
                }
                """
                
            config = types.LiveConnectConfig(
                system_instruction=system_instruction,
                response_modalities=["TEXT"],
                context_window_compression=types.ContextWindowCompressionConfig(
                    sliding_window=types.SlidingWindow(target_tokens=2000),
                ),
                session_resumption=types.SessionResumptionConfig(
                    handle=self.session_handle
                ),
                generation_config=types.GenerationConfig(
                    response_mime_type='application/json'
                ),
            )
            if self.session_handle:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Resuming {self.source_type} session with handle: {self.session_handle[:10]}...", flush=True)

            try:
                async with self.client.aio.live.connect(model=self.model, config=config) as session:
                    self.session = session
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Gemini {self.source_type} transcription session started", flush=True)

                    # Create tasks
                    capture_task = asyncio.create_task(self.capture_audio(external_stream))
                    send_task = asyncio.create_task(self.send_audio_to_gemini())
                    process_task = asyncio.create_task(self.process_responses())
                    self.tasks = [capture_task, send_task, process_task]

                    # Wait until tasks complete or are cancelled
                    await asyncio.gather(*self.tasks)
            except asyncio.CancelledError:
                # Expected on session resumption
                pass
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error in {self.source_type} Gemini transcriber: {e}", flush=True)
            finally:
                # Cancel any remaining tasks
                for task in self.tasks:
                    if not task.done():
                        task.cancel()
                # Clean up session
                self.session = None
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.source_type.capitalize()} Gemini session closed", flush=True)

            # Reconnect if a new handle was received
            if self._should_reconnect:
                self._should_reconnect = False
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Reconnecting {self.source_type} with new handle: {self.session_handle[:10]}...", flush=True)
                continue
            break
    
    def start(self, external_stream=None):
        """Start the transcriber in a background thread
        
        This AudioStreamer only handles the Gemini API integration. 
        Audio is expected to be fed via add_audio_chunk() method 
        from LiveTranscriptionManager in live_transcription.py.
        """
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
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.source_type.capitalize()} Gemini transcriber cleaned up", flush=True)

# async def main():
#     # This function serves as a standalone example when running this file directly
#     print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Gemini Live Audio Transcription Demo", flush=True)
    
#     # Create both mic and desktop streamers
#     mic_streamer = AudioStreamer(
#         transcription_callback=lambda text, source_type: print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎤 Mic: {text}"),
#         source_type="mic"
#     )
    
#     desktop_streamer = AudioStreamer(
#         transcription_callback=lambda text, source_type: print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔊 Desktop: {text}"),
#         source_type="desktop"
#     )
    
#     try:
#         # Start both streams
#         print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting microphone transcription...", flush=True)
#         await mic_streamer.start_mic_stream()
        
#         print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting desktop audio transcription...", flush=True)
#         await desktop_streamer.start_mic_stream()
        
#         # Run them both asynchronously
#         mic_task = asyncio.create_task(mic_streamer.run())
#         desktop_task = asyncio.create_task(desktop_streamer.run())
        
#         # Wait for both to complete (or until keyboard interrupt)
#         await asyncio.gather(mic_task, desktop_task)
    
#     except KeyboardInterrupt:
#         print(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping audio streams...", flush=True)
#     except Exception as e:
#         print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}", flush=True)
#     finally:
#         # Clean up both streamers
#         mic_streamer.cleanup()
#         desktop_streamer.cleanup()
#         print(f"[{datetime.now().strftime('%H:%M:%S')}] Audio transcription stopped", flush=True)

# if __name__ == "__main__":
#     asyncio.run(main())