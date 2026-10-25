from faster_whisper import WhisperModel


model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8",
)


def transcribe_audio(audio_path: str):
    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        language="en",
    )

    transcript_segments = []

    for segment in segments:
        transcript_segments.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip(),
        })

    return {
        "language": info.language,
        "segments": transcript_segments,
    }