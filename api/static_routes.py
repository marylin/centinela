"""Frontend static routes (kept as per-file routes deliberately: a directory
mount would expose node_modules etc., risk wrong content types for the
service worker on Windows hosts, and change error semantics)."""
import re

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse

router = APIRouter()

# New unified-UI assets: ES modules under web/js/ only, names allowlisted,
# content type pinned (module scripts hard-require a JS MIME type).
MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*\.js$")

@router.get("/next", response_class=HTMLResponse)
def read_next():
    """Preview path for the unified index UI (becomes / at cutover)."""
    try:
        with open("web/next.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/assets/js/{name}")
def read_module(name: str):
    """Serves the unified-UI ES modules."""
    if not MODULE_NAME_RE.match(name):
        raise HTTPException(status_code=404, detail="Unknown asset")
    try:
        with open(f"web/js/{name}", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/javascript")
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

@router.get("/app.js")
def read_js():
    """Serves the client-side JavaScript engine."""
    try:
        with open("web/app.js", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/javascript")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/style.css")
def read_css():
    """Serves the dashboard stylesheet."""
    try:
        with open("web/style.css", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/css")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/firebase-messaging-sw.js")
def read_sw():
    """Serves the Firebase Messaging Service Worker."""
    try:
        with open("web/firebase-messaging-sw.js", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/javascript")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

