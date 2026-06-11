"""Frontend static routes (kept as per-file routes deliberately: a directory
mount would expose node_modules etc., risk wrong content types for the
service worker on Windows hosts, and change error semantics)."""
import re

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

router = APIRouter()

# New unified-UI assets: ES modules under web/js/ only, names allowlisted,
# content type pinned (module scripts hard-require a JS MIME type).
MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*\.js$")

@router.get("/next", response_class=HTMLResponse)
def read_next():
    """Legacy preview alias: the unified UI is the root page since cutover."""
    return read_index()

@router.get("/assets/js/{name}")
def read_module(name: str):
    """Serves the unified-UI ES modules. no-cache so deploys propagate
    without stale-module sessions (modules are small; revalidation is cheap)."""
    if not MODULE_NAME_RE.match(name):
        raise HTTPException(status_code=404, detail="Unknown asset")
    try:
        with open(f"web/js/{name}", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/javascript",
                            headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown asset")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_class=HTMLResponse)
def read_index():
    """Serves the dashboard home page."""
    try:
        with open("web/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/style.css")
def read_css():
    """Serves the dashboard stylesheet."""
    try:
        with open("web/style.css", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/css",
                            headers={"Cache-Control": "no-cache"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

PAGE_NAMES = {"about", "technology", "privacy", "terms", "glossary"}

@router.get("/about", response_class=HTMLResponse)
@router.get("/technology", response_class=HTMLResponse)
@router.get("/privacy", response_class=HTMLResponse)
@router.get("/terms", response_class=HTMLResponse)
@router.get("/glossary", response_class=HTMLResponse)
def read_page(request: Request):
    """Plain-language site pages (about, technology, privacy, terms, glossary)."""
    name = request.url.path.strip("/")
    if name not in PAGE_NAMES:
        raise HTTPException(status_code=404, detail="Unknown page")
    try:
        with open(f"web/pages/{name}.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/manifest.json")
def read_manifest():
    """PWA manifest (installable app surface; iOS web push requires install)."""
    try:
        with open("web/manifest.json", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/manifest+json",
                            headers={"Cache-Control": "no-cache"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

ICON_NAME_RE = re.compile(r"^icon-(192|512)\.png$")

@router.get("/assets/icons/{name}")
def read_icon(name: str):
    if not ICON_NAME_RE.match(name):
        raise HTTPException(status_code=404, detail="Unknown asset")
    try:
        with open(f"web/icons/{name}", "rb") as f:
            return Response(content=f.read(), media_type="image/png")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown asset")

@router.get("/firebase-messaging-sw.js")
def read_sw():
    """Serves the Firebase Messaging Service Worker."""
    try:
        with open("web/firebase-messaging-sw.js", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/javascript")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

