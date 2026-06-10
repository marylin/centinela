"""Process-wide runtime state: environment, Firebase/Firestore clients, and
the two cross-domain mutable flags.

Import this module FIRST (api.main does): load_dotenv() must run before any
module-level os.environ reads elsewhere. Names assigned exactly once at import
(TESTING, db, firestore) may be from-imported; names REBOUND at runtime
(REOPENED_INCIDENT_ID) must be accessed as core.<name> so every module sees
the current value.
"""
import os

from dotenv import load_dotenv

load_dotenv()

import firebase_admin

TESTING = os.environ.get("TESTING", "false").lower() == "true"

# Initialize Firebase Admin SDK using Application Default Credentials (ADC)
try:
    firebase_admin.initialize_app()
    print("Firebase Admin SDK initialized successfully using ADC.")
except ValueError:
    pass
except Exception as e:
    print(f"Warning: Firebase Admin SDK failed to initialize: {e}")

# Initialize Firestore client with a fallback for local testing. `firestore`
# stays None under TESTING; call sites guard with `db is not None` before
# touching firestore.SERVER_TIMESTAMP etc.
db = None
firestore = None
try:
    if not TESTING:
        from firebase_admin import firestore
        db = firestore.client()
        print("Firestore client initialized successfully.")
except Exception as e:
    print(f"Warning: Failed to initialize Firestore client: {e}")

# Reopened-incident override (rebound at runtime; access as core.<name>).
REOPENED_INCIDENT_ID = None

# TESTING-mode database state toggle (mutated in place, never rebound).
MOCK_DB_STATE = {"populated": True}
