from pathlib import Path

from speaker_identification import identify_speaker

BASE_DIR = Path(__file__).resolve().parent
SPEAKER_CLIPS_DIR = BASE_DIR / "speaker_clips"


speaker_files = [
    SPEAKER_CLIPS_DIR / "speaker_00.wav",
    SPEAKER_CLIPS_DIR / "speaker_01.wav",
]


for speaker_file in speaker_files:
    print("\n" + "=" * 50)
    print(f"Identifying: {speaker_file.name}")
    print("=" * 50)

    results = identify_speaker(speaker_file)

    for result in results:
        print(
            f"{result['name']}: score={result['score']:.4f}, same_speaker={result['same_speaker']}"
        )
