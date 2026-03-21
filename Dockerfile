FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    websocket-client \
    requests \
    python-dotenv \
    pydantic

COPY bridge.py .
COPY templates/ templates/

RUN mkdir -p data

EXPOSE 8765

CMD ["python", "bridge.py"]
