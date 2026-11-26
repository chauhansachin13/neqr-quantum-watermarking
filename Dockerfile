FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml requirements.txt README.md LICENSE ./
COPY qwm ./qwm

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    useradd --create-home --shell /bin/bash qwm

USER qwm
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request, json; r=urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3); assert r.status==200 and json.loads(r.read())['status']=='ok'"

CMD ["qwm", "ui", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
