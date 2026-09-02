"""LINE's side of the bot: the webhook, the signature, and the model call.

Plain Starlette, and deliberately not FastAPI. `api_transformer` takes any
Starlette app, Reflex already depends on Starlette, and Reflex 0.9 pins
`starlette>=1.3.1` — which no released FastAPI accepts yet. One fewer dependency
and one fewer version fight.

Reflex mounts its own ASGI app *after* these routes
(`api_transformer.mount("", asgi_app)` in `reflex/app.py`), so anything declared
here wins and everything else falls through to Reflex — which is what lets the
page and the webhook share one process, one port and one owner gate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import store

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


def signature_ok(secret: str, body: bytes, header: str | None) -> bool:
    """LINE signs every delivery. Compared in constant time.

    `/callback` is deliberately outside the owner gate — LINE arrives with no
    session — so this signature is the only thing between the bot and anybody
    who guesses the URL, and the URL is the app's own hostname.
    """
    if not secret or not header:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), header)


async def ask_gemini(key: str, system: str, past: list[tuple[str, str]], text: str) -> str:
    contents = [
        {"role": "user" if role == "user" else "model", "parts": [{"text": body}]}
        for role, body in past
    ]
    contents.append({"role": "user", "parts": [{"text": text}]})
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system or store.DEFAULT_SYSTEM_PROMPT}]},
    }
    async with httpx.AsyncClient(timeout=25) as client:
        answer = await client.post(GEMINI, params={"key": key}, json=payload)
        answer.raise_for_status()
        body = answer.json()
    try:
        return body["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        # The model answered something this code does not understand. Saying so
        # is better than a silent non-reply, which reads as a dead bot.
        return "ขออภัย ตอนนี้ตอบไม่ได้ ลองใหม่อีกครั้งนะ"


async def reply(token: str, reply_token: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={"Authorization": f"Bearer {token}"},
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text[:4900]}]},
        )


async def callback(request: Request) -> Response:
    """LINE's webhook. Answers 200 to almost everything, on purpose.

    LINE retries and eventually disables a webhook that errors, so a bot that is
    not configured yet must still answer 200 — the failure belongs on the admin
    page, where somebody can act on it, not in LINE's dashboard.
    """
    raw = await request.body()
    conf = store.config()
    header = request.headers.get("x-line-signature")
    if not signature_ok(conf.get("line_channel_secret", ""), raw, header):
        # A body that says nothing: an unsigned caller learns only that the path
        # exists, which the hostname already told them.
        return JSONResponse({"ok": False})

    token = conf.get("line_channel_token", "")
    key = conf.get("gemini_api_key", "")
    for event in json.loads(raw or b"{}").get("events", []):
        if event.get("type") != "message" or event["message"].get("type") != "text":
            continue
        user = event["source"].get("userId", "unknown")
        text = event["message"]["text"]
        store.remember(user, "user", text)
        if not (token and key):
            continue
        answer = await ask_gemini(key, conf.get("system_prompt", ""), store.history(user), text)
        store.remember(user, "assistant", answer)
        await reply(token, event["replyToken"], answer)
    return JSONResponse({"ok": True})


async def healthz(request: Request) -> Response:
    """Asks the database, not the process — see `store.ready`."""
    reachable = store.ready()
    return JSONResponse(
        {"ok": reachable, "database": reachable, "configured": bool(store.config())}
    )


# ---------------------------------------------------------- the built frontend
#
# `reflex export --frontend-only --no-ssr` writes a static site into `.web/build/
# client`. Serving it from here is what makes this one process on one port: the
# alternative is Reflex's usual two services, and then `--access owner` would
# gate the page while leaving the events behind it open — a lock on the door of
# a room with no wall.
#
# Mounted at the export's own asset prefixes rather than at "/", because a mount
# at the root would swallow the Reflex routes that are appended after these.
BUILD = Path(__file__).resolve().parent.parent / ".web" / "build" / "client"

routes: list[Route | Mount] = [
    Route("/callback", callback, methods=["POST"]),
    Route("/healthz", healthz, methods=["GET"]),
]

if BUILD.is_dir():
    async def index(request: Request) -> Response:
        return FileResponse(BUILD / "index.html")

    routes.append(Route("/", index, methods=["GET"]))
    for asset in ("assets", "_next", "static"):
        if (BUILD / asset).is_dir():
            routes.append(Mount(f"/{asset}", StaticFiles(directory=BUILD / asset)))
    # Whatever the build left at the root — favicon.ico, robots.txt, the web
    # manifest — added one file at a time. **Never `Mount("/")`**: a mount at
    # the root matches by prefix and answers 404 itself for anything it does
    # not hold, so it would swallow `/_event` — the socket the page's state
    # runs on — and Reflex's routes are appended *after* these. The symptom
    # would be a page that loads and then does nothing at all.
    for entry in sorted(BUILD.iterdir()):
        if entry.is_file() and entry.name != "index.html":
            routes.append(
                Route(
                    f"/{entry.name}",
                    lambda request, path=entry: FileResponse(path),
                    methods=["GET"],
                )
            )

# **The schema is created at import, not in a lifespan.** Reflex mounts this
# app inside its own (`api_transformer.mount("", asgi_app)`) and then wraps the
# result in a third Starlette that owns the lifespan — and Starlette does not
# run the startup handlers of a *mounted* app. A `on_startup=[store.prepare]`
# here would look right, never fire, and the first save would fail with
# `relation "config" does not exist`. Which is exactly what it did.
store.prepare()

api = Starlette(routes=routes)
