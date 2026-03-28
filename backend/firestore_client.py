"""
Firestore client for RepWise session persistence.

Falls back gracefully when Firestore is not configured (local dev).
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy Firestore init
_db = None
_init_attempted = False


def _get_db():
    global _db, _init_attempted
    if _init_attempted:
        return _db
    _init_attempted = True
    try:
        from google.cloud import firestore
        _db = firestore.AsyncClient()
        logger.info("Firestore client initialized")
    except Exception as e:
        logger.warning(f"Firestore not available: {e}")
        _db = None
    return _db


async def save_session(session_dict: dict) -> Optional[str]:
    """Save a workout session to Firestore. Returns doc ID or None."""
    db = _get_db()
    if db is None:
        logger.info("Firestore not configured, skipping save")
        return None

    try:
        session_id = session_dict.get("session_id", "unknown")
        doc_ref = db.collection("sessions").document(session_id)
        await doc_ref.set(session_dict)
        logger.info(f"Session saved to Firestore: {session_id}")
        return session_id
    except Exception as e:
        logger.error(f"Firestore save failed: {e}")
        return None


async def get_session(session_id: str) -> Optional[dict]:
    """Get a session from Firestore."""
    db = _get_db()
    if db is None:
        return None

    try:
        doc = await db.collection("sessions").document(session_id).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"Firestore get failed: {e}")
        return None


async def get_user_sessions(user_id: str, limit: int = 20) -> list[dict]:
    """Get recent sessions for a user."""
    db = _get_db()
    if db is None:
        return []

    try:
        query = (
            db.collection("sessions")
            .where("user_id", "==", user_id)
            .order_by("start_time", direction="DESCENDING")
            .limit(limit)
        )
        sessions = []
        async for doc in query.stream():
            sessions.append(doc.to_dict())
        return sessions
    except Exception as e:
        logger.error(f"Firestore query failed: {e}")
        return []
