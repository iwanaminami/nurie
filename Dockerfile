FROM python:3.12-alpine
WORKDIR /app
COPY server.py event.html ogp.png apple-touch-icon.png logo.png logo-dark.png ./
VOLUME ["/app/data"]
ENV NURIE_DB=/app/data/nurie.db
EXPOSE 8378
RUN adduser -D -u 1001 nurie && chown -R nurie:nurie /app
USER nurie
CMD ["python3", "server.py"]
