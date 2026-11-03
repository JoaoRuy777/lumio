FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lumio_worker ./lumio_worker
CMD ["python", "-m", "lumio_worker"]
