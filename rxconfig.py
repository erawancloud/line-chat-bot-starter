"""Reflex configuration.

`api_url` is the address the compiled frontend calls for state events, and it is
baked in **at build time** — a wrong value here is a page that loads and then
does nothing, with no error on screen. On Erawan the app is one origin, so it is
the app's own public URL; `APP_URL` is set at build time in the Dockerfile.
"""

import os

import reflex as rx
from reflex_base.plugins.sitemap import SitemapPlugin

config = rx.Config(
    app_name="line_bot",
    # **Left as localhost on purpose, and it is the whole reason one image
    # deploys under any name.** `api_url` is baked into the compiled frontend,
    # so an absolute hostname ties a build to one address — wrong host and the
    # page loads and then does nothing, with no error on screen.
    #
    # Reflex's own client handles this, and it is worth knowing rather than
    # rediscovering: `getBackendURL` keeps a list of same-domain hostnames
    # (`localhost`, `0.0.0.0`, `::`) and, when the baked URL uses one of them,
    # rewrites the host to `window.location.hostname`, upgrades ws→wss and
    # http→https, and drops the port. So a build made against localhost talks
    # to whatever origin served the page. Empty string is not the answer —
    # the client does `new URL(...)` on it and the export fails outright.
    #
    # `APP_URL` overrides it for the unusual case of serving the frontend from
    # a different origin than the backend.
    api_url=os.environ.get("APP_URL", "http://localhost:8000"),
    # **No frontend_port here.** One process, one port: the exported frontend is
    # served by the same Starlette app that answers /callback, so there is no
    # second service to host, no reverse proxy inside the container, and one
    # owner gate covers both the page and the events behind it. Setting the
    # port anyway makes `reflex run --backend-only` refuse to start with
    # "Cannot specify --frontend-port when not running frontend".
    # One page, and it is behind an owner gate — a sitemap of it would be a
    # file telling crawlers about a door they cannot open.
    disable_plugins=[SitemapPlugin],
    # The theme belongs here since 0.8: `rx.App(theme=...)` is deprecated and
    # goes away at 1.0.
    plugins=[rx.plugins.RadixThemesPlugin(
        theme=rx.theme(appearance="light", accent_color="orange", radius="large")
    )],
)
