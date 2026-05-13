# Alerts editor UI

Source for the `alerts-editor` sidecar container in the Prometheus pod.
Background: [`specs/adr/0004-ui-workload-design.md`](../../specs/adr/0004-ui-workload-design.md).
Roadmap: [`specs/plans/0001-alerts-editor-implementation.md`](../../specs/plans/0001-alerts-editor-implementation.md).

## Layout

- `app.py` — FastAPI app. M1 is a stub page; M2/M3 add rule listing, editing and the
  `diff.yaml` write path.
- `requirements.txt` — runtime deps. Kept in sync with the `pip install` line in
  `_alerts_editor_layer` in [`../charm.py`](../charm.py) until we move to the baked image (see below).
- `Dockerfile` — for the eventual published image. **Not used in M1.**

## How the code reaches the container

**Milestone 1 (current):** the charm pushes `app.py` into a vanilla `python:3.12-slim`
container via `container.push()` at reconcile time, and the Pebble layer installs deps
on service start. No image build required — `juju refresh` ships new UI code.

**Milestone 3+ (planned):** build the image from this folder, publish to `ghcr.io`,
point `resources.alerts-editor-image.upstream-source` in
[`../../charmcraft.yaml`](../../charmcraft.yaml) at it, and drop the runtime pip install
from the layer.

## Local quick check

```sh
pip install -r requirements.txt
uvicorn app:app --reload --port 8080
# then visit http://localhost:8080
```

When run outside the pod, `/etc/prometheus/rules` won't exist and the page will say
"missing" for the shared volume — that is expected and proves the mount check works.
