from collections import defaultdict
from pathlib import Path

import torch
import torchaudio


def extract_speaker_audio(audio_path, speaker_segments):
    """
    Extract all audio belonging to each diarized speaker
    and combine it into one WAV file per speaker.
    """

    waveform, sample_rate = torchaudio.load(audio_path)

    # Convert stereo -> mono if necessary
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    # Resample to 16 kHz for speaker recognition
    if sample_rate != 16000:
        resampler = torchaudio.transforms.Resample(
            orig_freq=sample_rate,
            new_freq=16000,
        )

        waveform = resampler(waveform)
        sample_rate = 16000

    grouped_segments = defaultdict(list)

    for segment in speaker_segments:
        grouped_segments[segment["speaker"]].append(segment)

    output_dir = Path(__file__).parent / "speaker_clips"
    output_dir.mkdir(exist_ok=True)

    speaker_files = {}

    for speaker, segments in grouped_segments.items():
        clips = []

        for segment in segments:
            start_sample = int(segment["start"] * sample_rate)
            end_sample = int(segment["end"] * sample_rate)

            clip = waveform[:, start_sample:end_sample]

            if clip.numel() > 0:
                clips.append(clip)

        if not clips:
            continue

        combined_audio = torch.cat(clips, dim=1)

        output_path = output_dir / f"{speaker.lower()}.wav"

        torchaudio.save(
            str(output_path),
            combined_audio,
            sample_rate,
        )

        speaker_files[speaker] = str(output_path)

    return speaker_files
