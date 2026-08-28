FROM python:3.13-alpine
RUN addgroup -S receiver && adduser -S -G receiver receiver
WORKDIR /app
COPY --chown=receiver:receiver app.py ./app.py
USER receiver
EXPOSE 8080
CMD ["python", "app.py"]

