"""The admin page — Reflex, so the UI is Python too.

What this page is for: the owner pastes three keys and reads what the bot has
been saying. There is **no login on it**, and that is the design rather than an
omission — Erawan's `--access owner` puts Traefik's ForwardAuth in front of the
whole app, so the person is already identified before the request arrives. No
password to store, hash, reset or leak.

The one path that must stay outside that gate is `/callback`, because LINE
arrives with no session. `--public-path /callback` opens exactly that path
(`pathType: Exact`, so `/callback-admin` is not opened with it).
"""

from __future__ import annotations

import reflex as rx

from . import store
from .webhook import api

ACCENT = "#E07030"  # tea orange, the one accent


class State(rx.State):
    """Everything the page knows. Read on load, never held between requests."""

    token_set: str = ""
    secret_set: str = ""
    key_set: str = ""
    system_prompt: str = ""
    db_ready: bool = False
    rows: list[list[str]] = []
    saved: bool = False

    @rx.event
    def load(self):
        """Read the world once, when the page opens."""
        self.db_ready = store.ready()
        conf = store.config()
        self.token_set = store.mask(conf.get("line_channel_token", ""))
        self.secret_set = store.mask(conf.get("line_channel_secret", ""))
        self.key_set = store.mask(conf.get("gemini_api_key", ""))
        self.system_prompt = conf.get("system_prompt", "")
        self.rows = [list(row) for row in store.recent()]

    @rx.event
    def save(self, form: dict):
        """Blank fields keep what is stored — see `store.save`."""
        store.save(form)
        self.saved = True
        self.load()
        return rx.toast.success("Saved.")

    @rx.var
    def missing(self) -> list[str]:
        """What is still needed, in the order somebody would supply it."""
        out = []
        if not self.db_ready:
            out.append("database add-on")
        if not self.token_set:
            out.append("LINE channel token")
        if not self.secret_set:
            out.append("LINE channel secret")
        if not self.key_set:
            out.append("Gemini API key")
        return out

    @rx.var
    def answering(self) -> bool:
        return not self.missing

    @rx.var
    def webhook_url(self) -> str:
        """Read off the request, never configured.

        An owner who has to work out what to paste into LINE has been handed a
        puzzle whose answer was in the address bar the whole time.
        """
        url = str(self.router.url or "")
        if not url:
            return "/callback"
        scheme, _, rest = url.partition("://")
        host = rest.split("/", 1)[0]
        return f"{scheme}://{host}/callback" if host else "/callback"

    @rx.var
    def status(self) -> str:
        if self.answering:
            return "Configured — the bot is answering."
        return "Not answering yet. Still needed: " + ", ".join(self.missing)


def field(label: str, name: str, current: rx.Var, password: bool = True) -> rx.Component:
    """One key. The stored value is shown masked, never in full: enough to
    recognise which one is set, never enough to use it."""
    return rx.vstack(
        rx.hstack(
            rx.text(label, size="2", weight="medium"),
            rx.cond(
                current != "",
                rx.badge(current, color_scheme="green", variant="soft", size="1"),
                rx.badge("not set", color_scheme="orange", variant="soft", size="1"),
            ),
            align="center",
            spacing="2",
        ),
        rx.input(
            name=name,
            type="password" if password else "text",
            placeholder="leave blank to keep" if password else "",
            auto_complete=False,
            width="100%",
        ),
        spacing="1",
        width="100%",
        align="start",
    )


def step(number: str, title: str, *children) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.badge(number, radius="full", color_scheme="gray", size="1"),
                rx.heading(title, size="4"),
                align="center",
                spacing="3",
            ),
            *children,
            spacing="3",
            width="100%",
            align="start",
        ),
        width="100%",
    )


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.heading("LINE bot", size="7"),
                rx.spacer(),
                rx.cond(
                    State.answering,
                    rx.badge("live", color_scheme="green", variant="solid", size="2"),
                    rx.badge("setup", color_scheme="orange", variant="soft", size="2"),
                ),
                width="100%",
                align="center",
            ),
            rx.text(
                "Erawan signed you in before this page loaded, so there is no "
                "password here to steal.",
                color_scheme="gray",
                size="2",
            ),
            rx.callout(
                State.status,
                icon=rx.cond(State.answering, "check", "triangle_alert"),
                color_scheme=rx.cond(State.answering, "green", "orange"),
                width="100%",
            ),
            step(
                "1",
                "Give this URL to LINE",
                rx.text(
                    "LINE Developers → your channel → Messaging API → Webhook URL. "
                    "Paste it, press Verify, then switch Use webhook on.",
                    size="2",
                    color_scheme="gray",
                ),
                rx.hstack(
                    rx.code(State.webhook_url, size="2", variant="soft"),
                    rx.button(
                        "Copy",
                        on_click=rx.set_clipboard(State.webhook_url),
                        size="1",
                        variant="soft",
                    ),
                    align="center",
                    spacing="3",
                    width="100%",
                    wrap="wrap",
                ),
            ),
            step(
                "2",
                "Paste your keys",
                rx.text(
                    "They are stored in this app's own database, never in the "
                    "image and never handed to the agent that deployed it.",
                    size="2",
                    color_scheme="gray",
                ),
                rx.form(
                    rx.vstack(
                        field("LINE channel access token", "line_channel_token", State.token_set),
                        field("LINE channel secret", "line_channel_secret", State.secret_set),
                        field("Google Gemini API key", "gemini_api_key", State.key_set),
                        rx.vstack(
                            rx.text("System prompt", size="2", weight="medium"),
                            rx.text_area(
                                name="system_prompt",
                                default_value=State.system_prompt,
                                placeholder=store.DEFAULT_SYSTEM_PROMPT,
                                width="100%",
                                rows="3",
                            ),
                            spacing="1",
                            width="100%",
                            align="start",
                        ),
                        rx.button("Save", type="submit", style={"background": ACCENT}),
                        spacing="4",
                        width="100%",
                    ),
                    on_submit=State.save,
                    reset_on_submit=True,
                    width="100%",
                ),
            ),
            step(
                "3",
                "What it has been saying",
                rx.cond(
                    State.rows.length() > 0,
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("Who"),
                                rx.table.column_header_cell("Side"),
                                rx.table.column_header_cell("Message"),
                                rx.table.column_header_cell("When"),
                            )
                        ),
                        rx.table.body(
                            rx.foreach(
                                State.rows,
                                lambda row: rx.table.row(
                                    rx.table.cell(row[0]),
                                    rx.table.cell(row[1]),
                                    rx.table.cell(row[2]),
                                    rx.table.cell(row[3]),
                                ),
                            )
                        ),
                        variant="surface",
                        size="1",
                        width="100%",
                    ),
                    rx.text("Nothing yet.", size="2", color_scheme="gray"),
                ),
            ),
            rx.text(
                "erawan.cloud · this page is Reflex, the webhook is Starlette, "
                "and both are one process on one port.",
                size="1",
                color_scheme="gray",
                margin_top="1rem",
            ),
            spacing="5",
            width="100%",
            align="start",
        ),
        size="2",
        padding_y="3rem",
    )


app = rx.App(api_transformer=api)
app.add_page(index, route="/", title="LINE bot admin", on_load=State.load)
