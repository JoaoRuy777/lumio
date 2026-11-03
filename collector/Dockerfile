FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lumio_collector ./lumio_collector
COPY config ./config
EXPOSE 1162/udp
ENTRYPOINT ["python", "-m", "lumio_collector"]
CMD ["run", "--config", "config/coletor-exemplo.yaml"]
