# Build a partir da raiz do repositório: a API usa os drivers do coletor
# (mesmo código para "Testar conexão" e para a coleta).
FROM python:3.12-slim
WORKDIR /app
COPY collector/requirements.txt collector-requirements.txt
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -r collector-requirements.txt
COPY collector/lumio_collector ./lumio_collector
COPY api/lumio_api ./lumio_api
EXPOSE 8000
CMD ["uvicorn", "lumio_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
