FROM python:3.11-slim

# System deps: ffmpeg for audio decode, libsndfile for scipy audio I/O
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the faster-whisper model so first call isn't cold.
# Uses ~500 MB for 'small'. Change to 'medium' for better accuracy at ~1.5 GB.
ARG WHISPER_MODEL=small
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8'); print('Model cached.')"

COPY . .

EXPOSE 8765

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8765", "--log-level", "info", "--ws-ping-interval", "20", "--ws-ping-timeout", "60"]
