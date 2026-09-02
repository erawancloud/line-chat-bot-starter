# One image, one process, one port.
#
# Reflex normally runs two services — a Next-style frontend on 3000 and the
# backend on 8000. That shape does not fit here, and not only for tidiness:
# Erawan's `--access owner` gate is per app, so gating a separate frontend
# would leave the backend's `/_event` open, and the state behind the page is
# where the keys are set. A lock on the door of a room with no wall.
#
# So the frontend is *exported* at build time and served by the same Starlette
# app that answers `/callback`. Node is needed to build it and not to run it,
# which is what the two stages are for.

FROM python:3.13-slim AS build
WORKDIR /app

# Reflex fetches its own bun; these are what it needs to do it.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rxconfig.py .
COPY line_bot ./line_bot

# `--no-ssr` gives a static client the Python side can serve; `--frontend-only`
# because the backend here is just this source directory.
RUN reflex export --frontend-only --no-ssr --no-zip


FROM python:3.13-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    REFLEX_TELEMETRY_ENABLED=false

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rxconfig.py .
COPY line_bot ./line_bot
# The built page. `line_bot/webhook.py` looks for exactly this directory and
# serves nothing at all if it is missing — which is what a backend-only run
# looks like, rather than a crash.
COPY --from=build /app/.web/build/client ./.web/build/client

# Erawan's default, and what the platform routes to unless told otherwise.
EXPOSE 8000

# `--backend-only`: the frontend is already built and is served by the routes in
# `line_bot/webhook.py`. Reflex refuses this flag if `frontend_port` is set in
# rxconfig, which is why it is not.
CMD ["reflex", "run", "--env", "prod", "--backend-only", "--backend-port", "8000"]
