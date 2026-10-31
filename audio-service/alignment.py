def calculate_overlap(start_a, end_a, start_b, end_b):
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def align_speakers(transcript_segments, speaker_segments):
    aligned_segments = []

    for transcript in transcript_segments:
        best_speaker = "UNKNOWN"
        best_overlap = 0.0

        for speaker_segment in speaker_segments:
            overlap = calculate_overlap(
                transcript["start"],
                transcript["end"],
                speaker_segment["start"],
                speaker_segment["end"],
            )

            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker_segment["speaker"]

        aligned_segments.append(
            {
                "start": transcript["start"],
                "end": transcript["end"],
                "speaker": best_speaker,
                "text": transcript["text"],
            }
        )

    return aligned_segments
