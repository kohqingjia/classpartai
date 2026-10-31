def replace_speaker_labels(aligned_segments, speaker_identities):
    """
    Replace pyannote speaker labels with identified names.
    """

    identified_segments = []

    for segment in aligned_segments:
        speaker_label = segment["speaker"]

        name = speaker_identities.get(
            speaker_label,
            "UNKNOWN",
        )

        identified_segments.append(
            {
                "start": segment["start"],
                "end": segment["end"],
                "speaker": name,
                "original_speaker": speaker_label,
                "text": segment["text"],
            }
        )

    return identified_segments


def merge_consecutive_speaker_segments(segments):
    """
    Merge consecutive transcript segments belonging to the same speaker.

    Example:
        Tina: "Hello, I think..."
        Tina: "this could be useful."

    becomes:
        Tina: "Hello, I think... this could be useful."
    """

    if not segments:
        return []

    merged_segments = []

    current_segment = segments[0].copy()

    for segment in segments[1:]:
        # Same speaker -> combine the text
        if segment["speaker"] == current_segment["speaker"]:
            current_segment["end"] = segment["end"]

            current_segment["text"] = (
                current_segment["text"].rstrip() + " " + segment["text"].lstrip()
            )

        # Different speaker -> finish current turn
        else:
            merged_segments.append(current_segment)
            current_segment = segment.copy()

    # Add the final segment
    merged_segments.append(current_segment)

    return merged_segments
