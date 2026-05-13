# Image for the alerts-editor sidecar container.
#
# Milestone 1 of specs/plans/0001-alerts-editor-implementation.md does NOT use this
# Dockerfile yet — the charm pushes `app.py` into a vanilla `python:3.12-slim` and
# installs deps at service startup via the Pebble layer command. That keeps iteration
# fast (no image rebuild loop) while we stub out the UI.
#
# This file exists so that once the UI stabilises (M3+), we can:
#   docker build -t ghcr.io/<owner>/prometheus-alerts-editor:dev .
#   docker push ghcr.io/<owner>/prometheus-alerts-editor:dev
# and then point `resources.alerts-editor-image.upstream-source` in charmcraft.yaml
# at the published image, dropping the runtime pip install from the Pebble layer.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY templates/ ./templates/
COPY static/ ./static/

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
