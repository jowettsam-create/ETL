# GoodSAM -> REDCap web app (app.py) as a container.
# Build:  docker build -t goodsam-etl .
# Run:    docker run -d --name goodsam-etl -p 8501:8501 --env-file goodsam.env --restart unless-stopped goodsam-etl
# See HOSTING.md for the settings goodsam.env must contain.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Australia/Sydney

WORKDIR /app

COPY requirements.txt requirements-app.txt ./
RUN pip install -r requirements-app.txt

COPY GS2RCAPI.py app.py ./
COPY .streamlit/config.toml .streamlit/config.toml

# Run as a normal user, not root.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"

CMD ["python", "-m", "streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
