import soundcard as sc
import soundfile as sf

# Configuration
SAMPLERATE = 48000    # in Hz
DURATION    = 5       # in seconds
OUTPUT_FILE = "output.wav"

# 1. List loopback-capable microphones
mics = sc.all_microphones(include_loopback=True)
if not mics:
    raise RuntimeError("No loopback microphones found. Check WASAPI support or drivers.")

# 2. Find the loopback mic for the default speaker
default_spk = sc.default_speaker()
loop_mic = next(
    (m for m in mics if default_spk.name in m.name),
    None
)
if loop_mic is None:
    # Fallback: just take the first loopback mic
    loop_mic = mics[0]
print(f"Recording from: {loop_mic.name}")

# 3. Record audio
with loop_mic.recorder(samplerate=SAMPLERATE) as recorder:
    print(f"* Recording {DURATION}s of desktop audio...")
    audio_data = recorder.record(int(SAMPLERATE * DURATION))
print("* Recording complete")

# 4. Save to WAV
sf.write(OUTPUT_FILE, audio_data, SAMPLERATE)
print(f"Saved to '{OUTPUT_FILE}'")
