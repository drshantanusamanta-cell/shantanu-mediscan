# Dockerfile for Hugging Face Spaces (Docker SDK + Streamlit)
# HF deprecated the native Streamlit SDK, so Streamlit apps now ship as Docker.
# Not needed for Streamlit Community Cloud — harmless to keep in the repo.

FROM python:3.11-slim

# HF Spaces runs containers as UID 1000
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

USER user
EXPOSE 8501

HEALTHCHECK CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=5).status == 200 else 1)"

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=false"]
