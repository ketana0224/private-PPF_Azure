FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY data ./data

EXPOSE 8000
ENV HOST=0.0.0.0 PORT=8000

CMD ["python", "server.py"]
