import json
import sys

from transcription import transcribe_audio


def main():
    if len(sys.argv) != 2:
        raise ValueError(
            "Usage: python transcription_worker.py <audio_path>"
        )

    audio_path = sys.argv[1]
    result = transcribe_audio(audio_path)

    # Only JSON should be written to stdout.
    print(json.dumps(result))


if __name__ == "__main__":
    main()