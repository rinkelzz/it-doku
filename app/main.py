"""Einstiegspunkt der IT-Dokumentation."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import csrf
from .config import settings
from .db import connect, init_db
from .dsm import write_ui_config
from .dsm_auth import proxy_info, publish_proxy_files
from . import scheduler
from .routers import (auth, backup, branding, contacts, devices, files, licenses, network, overview, settings as settings_router,
                      updates, users)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    conn = connect()
    try:
        write_ui_config(conn)
        publish_proxy_files()
    finally:
        conn.close()
    if settings.scheduler:
        scheduler.start()
    if settings.update_check:
        from . import updates
        updates.check_in_background()  # gleich beim Start, damit die Paketquelle sofort etwas liefert
    yield
    scheduler.stop()


app = FastAPI(
    title="IT-Dokumentation",
    version=__version__,
    description="IT-Dokumentation pro Kunde: Geräte, Lizenzen, Netzwerk, Ansprechpartner und Zugangsdaten (verschlüsselt) auf der Synology NAS.",
    root_path=settings.root_path,
    lifespan=lifespan,
)

# Echte Absenderadresse hinter dem Reverse Proxy (X-Forwarded-For/-Proto) – aber nur, wenn die Anfrage
# von der NAS selbst kommt (DSM-Reverse-Proxy, 127.0.0.1). Direkt aus dem Netz mitgeschickte Header werden
# ignoriert; bei einer Kette zählt die letzte Adresse, die nicht von der NAS stammt (die trägt der Proxy ein).
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware  # noqa: E402

TRUSTED_PROXIES = ["127.0.0.1", "::1"]
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=TRUSTED_PROXIES)


class _RememberPeer:
    """Merkt sich die echte TCP-Gegenstelle, bevor X-Forwarded-For sie umschreibt
    (für die Prüfung, ob eine Anfrage wirklich von ui/app.cgi auf der NAS kommt)."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            scope["itd_peer"] = client[0] if client else ""
        await self.app(scope, receive, send)


app.add_middleware(_RememberPeer)  # zuletzt hinzugefügt = läuft zuerst

for r in (auth.router, backup.router, branding.router, settings_router.router, updates.router, users.router,
          overview.router, network.router, devices.router, licenses.router, contacts.router, files.router):
    app.include_router(r)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    reason = csrf.blocked(request.method, request.url.path, request.headers)
    if reason:
        return JSONResponse({"detail": reason}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def no_cache_for_api(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index(request: Request):
    # Versionsnummer an CSS/JS hängen, damit nach einem Update nichts Altes aus dem Cache kommt.
    # Im DSM-Fenster laufen alle Adressen über app.cgi?p=… (gleicher Ursprung wie DSM).
    proxied = proxy_info(request)
    base = (proxied["base"] + "?p=/") if proxied else ""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace("{{v}}", __version__)
    html = html.replace('"static/', '"' + base + "static/")
    html = html.replace("<head>", "<head>\n<script>window.ITD_PROXY=" + ("\"" + proxied["base"] + "\"" if proxied else "null") + ";</script>", 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/v1/health", tags=["System"])
def health():
    """Ohne Login – für DSM-Statusprüfung und Reverse-Proxy-Checks."""
    return {"status": "ok", "version": __version__}


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        proxy_headers=False,  # übernimmt die Middleware oben (nur 127.0.0.1/::1 vertraut)
    )


if __name__ == "__main__":
    run()
