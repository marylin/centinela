"""Centinela backend: composition root.

api.core MUST be imported first (it runs load_dotenv() before any module-level
os.environ reads in the other api modules). Everything else lives in domain
modules; this file is app + CORS + router includes only.

Domain map: core (env/clients/flags), config (registry + constants), stores
(Firestore + fallbacks), resolution (derived coordinates), hazard (model
index + weather recorder), demo (read-time merge), narration (Gemini caches),
places_resolver/watchlist (pure logic), and one router module per surface:
risk, incidents, push, alert, connectors, conditions, seismic, static,
places, watchlist, demo.
"""
import api.core  # noqa: F401  (first: dotenv + Firebase/Firestore init)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.risk_routes import router as risk_router
from api.incident_routes import router as incident_router
from api.push_routes import router as push_router
from api.alert_routes import router as alert_router
from api.connector_routes import router as connector_router
from api.conditions_routes import router as conditions_router
from api.seismic_routes import router as seismic_router
from api.static_routes import router as static_router
from api.places_routes import router as places_router
from api.watchlist_routes import router as watchlist_router
from api.demo_routes import router as demo_router

app = FastAPI(title="Centinela Backend API")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(risk_router)
app.include_router(incident_router)
app.include_router(push_router)
app.include_router(alert_router)
app.include_router(connector_router)
app.include_router(conditions_router)
app.include_router(seismic_router)
app.include_router(static_router)
app.include_router(places_router)
app.include_router(watchlist_router)
app.include_router(demo_router)
