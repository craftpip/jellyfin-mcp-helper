FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uvicorn[standard]==0.35.0 fastapi==0.116.1 httpx==0.28.1 pydantic==2.11.7 pydantic-settings==2.10.1 guessit==3.8.0

WORKDIR /app

EXPOSE 18327
EXPOSE 18329

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18327"]