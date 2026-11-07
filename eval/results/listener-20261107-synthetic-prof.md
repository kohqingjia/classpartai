# Listener evaluation (2026-11-07)

7 scripted demo seminars (9.3 min, 64 lines), real models, run once in the app container (`eval/listener/collect.py`), scored offline from the cache (`eval/listener/compare.py`). Speaker outcomes are per script line; see `src/classpartai/listener_eval.py` for the rules.

## Speaker attribution

| Configuration | Credited to wrong student | Student lines right | Student wrong | Student unattributed | Professor right | Professor wrong | Guest left unattributed | Speech credited to wrong student | Speech wrongly given to a professor |
|---|---|---|---|---|---|---|---|---|---|
| A · diarised + Tina's rule (current) | 0 | 17/26 | 1 | 8 | 35/36 | 0 | 2/2 | 0.4 s | 7.6 s |
| B · 0.35 / 0.10 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| C · 0.35 / 0.10 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.35 / 0.10 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| W · 0.35 / 0.10 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W+veto · 0.35 / 0.10 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| **the app now** (`decide_speakers`, = W+veto) | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| oracle line spans · 0.35 / 0.10 | 0 | 26/26 | 0 | 0 | 36/36 | 0 | 2/2 | 0.0 s | 0.0 s |

### Threshold grid (min score / min margin)

| Configuration | Credited to wrong student | Student lines right | Student wrong | Student unattributed | Professor right | Professor wrong | Guest left unattributed | Speech credited to wrong student | Speech wrongly given to a professor |
|---|---|---|---|---|---|---|---|---|---|
| B · 0.25 / 0.05 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| B · 0.25 / 0.10 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| B · 0.25 / 0.15 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| B · 0.35 / 0.05 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| B · 0.35 / 0.10 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| B · 0.35 / 0.15 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| B · 0.45 / 0.05 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| B · 0.45 / 0.10 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| B · 0.45 / 0.15 | 1 | 24/26 | 2 | 0 | 35/36 | 0 | 2/2 | 2.0 s | 7.6 s |
| C · 0.25 / 0.05 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| C · 0.25 / 0.10 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| C · 0.25 / 0.15 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| C · 0.35 / 0.05 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| C · 0.35 / 0.10 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| C · 0.35 / 0.15 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| C · 0.45 / 0.05 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| C · 0.45 / 0.10 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| C · 0.45 / 0.15 | 0 | 25/26 | 1 | 0 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.25 / 0.05 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.25 / 0.10 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.25 / 0.15 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.35 / 0.05 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.35 / 0.10 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.35 / 0.15 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.45 / 0.05 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.45 / 0.10 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| B+veto · 0.45 / 0.15 | 0 | 24/26 | 1 | 1 | 35/36 | 0 | 2/2 | 0.6 s | 7.6 s |
| W · 0.25 / 0.05 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W · 0.25 / 0.10 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W · 0.25 / 0.15 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W · 0.35 / 0.05 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W · 0.35 / 0.10 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W · 0.35 / 0.15 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W · 0.45 / 0.05 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W · 0.45 / 0.10 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W · 0.45 / 0.15 | 1 | 25/26 | 1 | 0 | 36/36 | 0 | 2/2 | 1.6 s | 0.1 s |
| W+veto · 0.25 / 0.05 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| W+veto · 0.25 / 0.10 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| W+veto · 0.25 / 0.15 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| W+veto · 0.35 / 0.05 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| W+veto · 0.35 / 0.10 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| W+veto · 0.35 / 0.15 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| W+veto · 0.45 / 0.05 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| W+veto · 0.45 / 0.10 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |
| W+veto · 0.45 / 0.15 | 0 | 25/26 | 0 | 1 | 36/36 | 0 | 2/2 | 0.1 s | 0.1 s |

## Transcription

Pipeline transcript (Whisper base int8, beam 5) against the script:

| Demo | Audio | WER | Speakers in script | Diarised speakers | Whisper | pyannote | Pipeline total |
|---|---|---|---|---|---|---|---|
| 01-everyone | 107 s | 1.1% (3/262) | 5 | 5 | 15 s | 210 s | 325 s |
| 02-one-silent | 73 s | 2.6% (5/191) | 4 | 4 | 11 s | 133 s | 209 s |
| 03-nobody | 51 s | 2.9% (4/136) | 1 | 1 | 9 s | 84 s | 121 s |
| 04-misconception | 88 s | 3.0% (6/202) | 5 | 5 | 13 s | 166 s | 256 s |
| 05-injection | 69 s | 5.0% (8/160) | 5 | 5 | 10 s | 120 s | 207 s |
| 06-dominant | 98 s | 3.2% (7/220) | 5 | 4 | 15 s | 175 s | 260 s |
| 07-guest | 72 s | 6.0% (11/182) | 5 | 5 | 11 s | 130 s | 214 s |
| **all** | | **3.3%** (44/1353) | | | | | |

Model size and beam width (same CPU, run one after another):

| Whisper | Beam | WER | Transcription time | Real-time factor |
|---|---|---|---|---|
| tiny | 5 | 4.1% | 45 s | 0.08 |
| base | 1 | 3.6% | 49 s | 0.09 |
| base | 5 | 3.3% | 76 s | 0.14 |
| base | 5 + word timings | 3.3% | 77 s | 0.14 |
| small | 5 | 2.4% | 189 s | 0.34 |

## Reading

- **What the professor saw before (A).** Tina's rule ("ambiguous when more than one enrolled
  voice passes SpeechBrain's 0.25") left 8 of 26 student lines unattributed although every one
  had a clear winner: Tasmin and Tina score about 0.25 against each other's sample (e.g. Tasmin
  0.79 vs Tina 0.27), so both pass. It never credited a whole line to the wrong student, but
  0.4 s of speech was, and 7.6 s of students' speech went to the professor: Whisper's segments
  often run across a turn change and the pipeline gives the whole segment to one speaker.
- **Score/margin per diarised speaker (B)** names all of them, but in 06-dominant pyannote
  merged Tina and Tasmin into one speaker (Tina 0.68, Tasmin 0.37), so Tasmin's line was
  credited to Tina: the dangerous error. No threshold in the grid prevents it (the grid is flat:
  on these recordings a speaker's own voice scores 0.46 to 0.97 and anyone else's at most 0.37).
- **Per-sentence matching without diarisation (C)** happens to be right here, but each short
  sentence carries little voice, and the turn-change error remains.
- **Words aligned to speaker turns (W)** removes the turn-change error (7.6 s to 0.1 s given
  to the professor) but keeps B's merged-speaker error.
- **W + veto (now the app's Listener)**: words go to the diarised turn they fall in, each
  speaker is named by score/margin, and each line of 1 s or more is checked on its own voice;
  a line that clearly sounds like someone else becomes "ambiguous". No line, and 0.1 s of
  speech (one word-timing edge of 80 ms), is credited to the wrong student; 25/26 student lines
  are right and the remaining one (the merged-speaker line) is safely unattributed; all 36
  professor lines are right. The row "the app now" runs the shipped `decide_speakers` on the
  cache and must equal W+veto.
- **The voice model itself is not the bottleneck**: scored on each line's true time span
  (oracle), every line is right. The errors came from segmentation and diarisation.
- **Thresholds**: kept at 0.35 / 0.10; every value in the grid gives the same result here, so
  the data cannot tell them apart.
- **Whisper**: base, beam 5 (what the app runs) is 3.3% WER. Word timings cost nothing extra.
  small is 2.4% for 2.5x the transcription time (still under 10% of the pipeline, since
  pyannote takes 64% of it); tiny 4.1%; base with beam 1 3.6%. Most errors are names ("Le
  Young") and spelling of terms. Kept base: switching is a one-line change but needs the model
  downloaded on the server.
- **Runtime** (4-core shared CPU, another job running): the pipeline took 1,593 s for 556 s of
  audio (2.9x real time): pyannote 1,017 s, Whisper 84 s, and about 490 s extracting and
  identifying speakers, because `identify_speaker` re-embeds every enrolled sample for every
  comparison. The veto adds about 52 s for 103 lines, using each sample's embedding once.

Caveats: 7 scripted recordings with synthetic (cloned) voices, no crosstalk or room noise, and
26 student lines, so small differences are one line. The "guest" in 07-guest is voiced by the
enrolled demo voice "Prof Demo" (0.95), so the guest check passes only because that voice is on
no class list.
