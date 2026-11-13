FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN test -s ai/bot_model.joblib || python -m ai.train
USER 65534:65534
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--no-proxy-headers","--no-access-log"]
