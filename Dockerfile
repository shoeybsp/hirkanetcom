FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system --gid 10001 app && adduser --system --uid 10001 --ingroup app app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data /app/uploads /app/static/uploads && chown -R app:app /app
USER app
EXPOSE 5000
CMD ["gunicorn","--config","gunicorn.conf.py","api.app:app"]
