FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lumio_sim ./lumio_sim
COPY config ./config
EXPOSE 8080 16101-16110/udp
CMD ["python", "-m", "lumio_sim", "--config", "config/rede-exemplo.yaml"]
