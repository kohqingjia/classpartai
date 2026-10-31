from pipeline import process_audio

audio_path = "audio-service/enrollments/seminar_test.m4a"

result = process_audio(audio_path)


print("\n--- IDENTIFIED SPEAKER TRANSCRIPT ---\n")

print(f"Language: {result['language']}\n")


for segment in result["segments"]:
    print(
        f"[{segment['start']:.1f}s → {segment['end']:.1f}s] {segment['speaker']}: {segment['text']}"
    )
