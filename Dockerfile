# ClassPart AI demo: Streamlit front end + the audio-service Listener pipeline, CPU only.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch's CPU index first, so torch/torchaudio don't pull the multi-GB CUDA builds.
COPY audio-service/requirements.txt audio-service/requirements.txt
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        -r audio-service/requirements.txt \
        "streamlit>=1.50" "openai>=1.60" "agentmail>=0.1" "pydantic>=2.8"

COPY app.py ./
COPY .streamlit ./.streamlit
COPY src ./src
COPY data ./data
COPY audio-service ./audio-service

# Models, voice samples, per-speaker clips and app data (class list, emails, audit log) are
# written at runtime; the volumes in deploy/compose.yaml keep all but the clips.
RUN useradd --uid 10001 --create-home app \
    && mkdir -p /data audio-service/enrollments audio-service/models audio-service/speaker_clips \
    && chown -R app:app /data audio-service
USER app

ENV HF_HOME=/data/hf \
    CLASSPARTAI_DATA_DIR=/data/app \
    PYTHONPATH=/app/src \
    TORCH_HOME=/data/torch \
    PYTHONUNBUFFERED=1

EXPOSE 8501
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", \
     "--server.maxUploadSize=200", "--browser.gatherUsageStats=false"]
