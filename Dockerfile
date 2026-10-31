FROM python:3.12-alpine
WORKDIR /app
COPY server.py event.html ogp.png apple-touch-icon.png logo.png logo-dark.png ./
VOLUME ["/app/data"]
ENV NURIE_DB=/app/data/nurie.db
EXPOSE 8378
CMD ["python3", "server.py"]
