# Deploying the demo

The demo runs on QJ's VPS as one container (`classpartai-app`) behind the shared Caddy in `~/stardyhub`, at https://classpartai.187-52-125-31.sslip.io (password protected).

## First deploy

```bash
git clone https://github.com/kohqingjia/classpartai.git ~/apps/classpartai
cd ~/apps/classpartai
cp .env.example .env        # set HF_TOKEN; accept the terms on
                            # https://huggingface.co/pyannote/speaker-diarization-community-1
docker compose -f deploy/compose.yaml up -d --build
```

## Update

```bash
cd ~/apps/classpartai && git pull
docker compose -f deploy/compose.yaml up -d --build
```

The first recording after a (re)start is slow while the Whisper, pyannote and SpeechBrain models load. Models and voice samples live in Docker volumes, so they survive rebuilds.
