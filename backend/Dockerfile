FROM python:3.11-slim

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY novel_deconstructor ./novel_deconstructor

EXPOSE 8000
CMD ["uvicorn", "novel_deconstructor.main:app", "--host", "0.0.0.0", "--port", "8000"]
