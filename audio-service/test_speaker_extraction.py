from diarization import diarize_audio
from speaker_extraction import extract_speaker_audio

audio_path = "audio-service/enrollments/seminar_test.m4a"

print("Running diarization...")

speaker_segments = diarize_audio(audio_path)

print("\nDiarization results:")

for segment in speaker_segments:
    print(segment)


print("\nExtracting speaker audio...")

speaker_files = extract_speaker_audio(
    audio_path,
    speaker_segments,
)

print("\nSpeaker files:")

for speaker, file_path in speaker_files.items():
    print(f"{speaker} -> {file_path}")
