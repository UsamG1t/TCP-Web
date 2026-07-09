FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# 'app:app' = the Flask object in app.py; engine/ is copied alongside
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]
