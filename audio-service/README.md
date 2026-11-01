# ClassPart AI — Audio Processing Service

This service processes seminar audio to generate a timestamped transcript with identified speakers. It currently implements the core audio-processing functionality for **CPA-18, CPA-19, and CPA-20**.

## Current Functionality

The audio pipeline currently supports:

### CPA-18 — Speech Transcription

Uses **Faster-Whisper** to transcribe seminar audio into timestamped text segments.

Example:

```text
[0.0s → 5.2s] I think artificial intelligence could help...
```

English is explicitly specified during transcription to improve recognition accuracy for seminar recordings.

### CPA-19 — Speaker Diarization

Uses **Pyannote** to detect when different speakers are speaking.

Pyannote initially assigns anonymous speaker labels such as:

```text
SPEAKER_00
SPEAKER_01
SPEAKER_02
```

Transcript segments are then aligned with the diarization output based on timestamp overlap.

### CPA-20 — Speaker Identification

Uses **SpeechBrain ECAPA-TDNN speaker recognition** to compare each diarized speaker against registered speaker voice samples.

The pipeline:

```text
Seminar Audio
      ↓
Faster-Whisper
      ↓
Timestamped Transcript
      ↓
Pyannote Diarization
      ↓
SPEAKER_00 / SPEAKER_01 / ...
      ↓
Speaker Audio Extraction
      ↓
SpeechBrain Speaker Recognition
      ↓
Registered Speaker Names
      ↓
Merged Speaker Turns
      ↓
Final Identified Transcript
```

For example:

```text
[0.0s → 8.0s] Student A: I think using artificial intelligence...
[8.0s → 20.6s] Student B: I agree, but I think there could be privacy concerns...
```

Consecutive transcription segments belonging to the same speaker are merged into a single contribution turn.

---

## Main Components

```text
audio-service/
├── alignment.py
├── diarization.py
├── pipeline.py
├── speaker_extraction.py
├── speaker_identification.py
├── speaker_mapping.py
├── transcription.py
├── transcription_worker.py
├── test_pipeline.py
├── test_speaker_extraction.py
├── test_speaker_identification.py
└── requirements.txt
```

### `transcription.py`

Runs Faster-Whisper and produces timestamped transcription segments.

### `transcription_worker.py`

Runs transcription in a separate Python process.

This is intentional because Faster-Whisper uses **PyAV**, while the current Pyannote/TorchCodec stack may use a different FFmpeg library. On macOS, loading both into the same Python process can result in conflicting FFmpeg/AVFoundation libraries.

Keeping transcription in a separate process avoids this conflict.

### `diarization.py`

Runs Pyannote speaker diarization.

The service automatically selects the best available PyTorch processing device:

```text
CUDA → Windows/Linux with compatible NVIDIA GPU
MPS  → Apple Silicon Mac
CPU  → Fallback
```

CPU processing is supported but diarization may take longer.

### `alignment.py`

Aligns Whisper transcript segments with Pyannote speaker segments based on timestamp overlap.

### `speaker_extraction.py`

Collects the audio associated with each diarized speaker and creates a speaker-specific audio sample for identification.

### `speaker_identification.py`

Uses SpeechBrain speaker recognition to compare diarized speaker samples against registered speakers.

### `speaker_mapping.py`

Replaces anonymous labels such as `SPEAKER_00` with identified names and merges consecutive transcript segments belonging to the same speaker.

### `pipeline.py`

Orchestrates the complete audio-processing pipeline.

---

# Setup

## 1. Pull the Latest Code

From the project repository:

```bash
git pull
```

Move to the project root if necessary:

```bash
cd classpartai
```

---

## 2. Create a Python Virtual Environment

The audio service uses its own Python environment.

From the project root:

```bash
python3 -m venv audio-service/.venv
```

Activate it.

### macOS / Linux

```bash
source audio-service/.venv/bin/activate
```

### Windows PowerShell

```powershell
audio-service\.venv\Scripts\Activate.ps1
```

After activation, the terminal should show something similar to:

```text
(.venv)
```

---

## 3. Install Python Dependencies

With the virtual environment activated:

```bash
pip install -r audio-service/requirements.txt
```

The main ML libraries used by the service include:

- Faster-Whisper
- Pyannote Audio
- SpeechBrain
- PyTorch
- TorchAudio
- TorchCodec
- PyAV
- python-dotenv

---

## 4. Install FFmpeg

FFmpeg is required for audio processing.

### macOS

Using Homebrew:

```bash
brew install ffmpeg
```

Verify:

```bash
ffmpeg -version
```

### Windows

Install FFmpeg and ensure the FFmpeg executable is available in the system `PATH`.

Verify from PowerShell or Command Prompt:

```powershell
ffmpeg -version
```

---

## 5. Configure Hugging Face Access

Pyannote requires Hugging Face model access.

Create a `.env` file in the **root of the `classpartai` repository** if one does not already exist.

Add:

```text
HF_TOKEN=your_huggingface_token
```

Do not commit the `.env` file to GitHub.

Each developer should use their own Hugging Face token.

You may also need to accept the access conditions for the Pyannote model used by the project on Hugging Face before the model can be downloaded.

---

# Running the Pipeline

Ensure the virtual environment is activated:

```bash
source audio-service/.venv/bin/activate
```

Then run:

```bash
python audio-service/test_pipeline.py
```

The first run may take longer because the required ML models may need to be downloaded and cached locally.

A successful run should progress through:

```text
Diarization device: mps
Transcribing...
Diarizing...
Aligning transcript with speakers...
Extracting speaker audio...
Identifying speakers...
Merging consecutive speaker turns...
```

The device may display `cuda`, `mps`, or `cpu` depending on the machine.

The final result should be an identified transcript similar to:

```text
--- IDENTIFIED SPEAKER TRANSCRIPT ---

Language: en

[0.0s → 8.0s] Student A: ...
[8.0s → 20.6s] Student B: ...
[20.6s → 28.9s] Student A: ...
```

---

# Testing Individual Components

The complete pipeline can be tested with:

```bash
python audio-service/test_pipeline.py
```

Speaker extraction can be tested independently with:

```bash
python audio-service/test_speaker_extraction.py
```

Speaker identification can be tested independently with:

```bash
python audio-service/test_speaker_identification.py
```

These tests are useful when debugging individual parts of the pipeline without rerunning every stage.

---

# Notes and Current Limitations

### Processing Time

Speaker diarization is computationally intensive.

The service automatically uses:

- CUDA when a compatible NVIDIA GPU is available
- MPS on supported Apple Silicon Macs
- CPU otherwise

CPU-only machines may therefore take significantly longer to process seminar recordings.

### Speaker Labels

Pyannote speaker labels such as `SPEAKER_00` are temporary identifiers for a particular recording. They should not be assumed to represent the same person across different recordings.

SpeechBrain speaker identification is therefore used to map these temporary labels to registered speakers.

### Transcript/Speaker Boundary Alignment

Whisper transcription segments and Pyannote diarization segments are generated independently.

The current implementation assigns each Whisper segment to the speaker with the greatest timestamp overlap.

As a result, if a Whisper segment crosses a speaker-change boundary, a small portion of one speaker's speech may occasionally be assigned to the next speaker.

This is a known limitation of the current prototype and can be improved with more fine-grained alignment later.

### Speaker Identification

Speaker identification is currently based on comparison against registered voice samples.

The current implementation is intended as a prototype for suggesting speaker identities. Future integration should allow the professor to review or correct uncertain speaker matches rather than treating every automated identification as final.

---

# Current Status

The backend feasibility for the following tasks has been implemented:

- **CPA-18:** Transcribe seminar audio into timestamped turns
- **CPA-19:** Separate speakers and keep repeated appearances linked within a recording
- **CPA-20:** Identify diarized speakers using registered voice samples

The current pipeline therefore demonstrates:

```text
Seminar Recording
        ↓
Transcription
        ↓
Speaker Diarization
        ↓
Speaker Identification
        ↓
Named, Timestamped Seminar Transcript
```

This output can subsequently be used by the participation assessment and agent components of ClassPart AI.
