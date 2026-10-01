FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.lock.txt /app/backend/requirements.lock.txt
RUN pip install --no-cache-dir -r backend/requirements.lock.txt
COPY src /app/src
COPY backend /app/backend
COPY config.yaml main.py /app/
RUN mkdir -p /app/data /app/results/logs /var/backtest/data /var/backtest/results/logs
EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
