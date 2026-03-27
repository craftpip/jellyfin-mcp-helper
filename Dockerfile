FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY README.md ./README.md

RUN mkdir -p /app/logs /app/reports

EXPOSE 18327

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18327"]
