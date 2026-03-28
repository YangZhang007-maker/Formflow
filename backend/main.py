import asyncio
import base64
import json
import logging
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from backend.agent import formflow_agent
from backend.sessions import SessionManager
from backend import firestore_client
from backend.summary import generate_coaching_summary
from backend.workout_planner import (
    CheckInData,
    ExercisePlan,
    generate_workout,
    generate_warmup,
    adapt_exercise,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_NAME = "formflow"
app = FastAPI(title="Formflow", version="1.0.0")


# No-cache for static files
from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

app.add_middleware(NoCacheMiddleware)

# ADK session service (for Gemini live sessions)
adk_session_service = InMemorySessionService()
runner = Runner(
    app_name=APP_NAME,
    agent=formflow_agent,
    session_service=adk_session_service,
)

# Workout session manager
session_mgr = SessionManager()


# --- Session API models ---

class StartSessionRequest(BaseModel):
    user_id: str
    exercise: str

class RepEventRequest(BaseModel):
    session_id: str
    form_quality: str = "good"

class EndSessionRequest(BaseModel):
    session_id: str

class GenerateWorkoutRequest(BaseModel):
    goal: str = "general"
    time_minutes: int = 25
    equipment: str = "none"
    energy: str = "medium"
    soreness: list[str] = []
    target_muscles: list[str] = []
    level: str = "beginner"
    crowded_gym: bool = False
    low_confidence: bool = False
    user_context: str = ""

class AdaptExerciseRequest(BaseModel):
    exercise: str
    reason: str
    session_context: str = ""

class RescueRequest(BaseModel):
    exercise: str
    reason: str  # equipment_busy, low_energy, running_out_of_time, discomfort, dont_know, easier
    remaining_exercises: list[str] = []
    session_context: str = ""

class SaveProfileRequest(BaseModel):
    user_id: str
    level: str = "beginner"
    preferred_goal: str | None = None
    preferred_equipment: str | None = None
    crowded_gym: bool = False
    low_confidence: bool = False

class ExerciseInput(BaseModel):
    exercise: str

class WarmupRequest(BaseModel):
    exercises: list[ExerciseInput]


# --- Session APIs ---

@app.post("/session/start")
async def start_session(req: StartSessionRequest):
    """Start a new workout session."""
    session = session_mgr.start_session(req.user_id, req.exercise)
    logger.info(f"Session started: {session.session_id} ({session.exercise})")
    return {
        "session_id": session.session_id,
        "exercise": session.exercise,
        "start_time": session.start_time,
    }


@app.post("/session/rep")
async def record_rep(req: RepEventRequest):
    """Record a rep event."""
    rep = session_mgr.add_rep(req.session_id, req.form_quality)
    if rep is None:
        return {"error": "Session not found or ended"}
    session = session_mgr.get_session(req.session_id)
    return {
        "rep_number": rep.rep_number,
        "total_reps": session.total_reps,
        "form_score": session.form_score,
    }


@app.post("/session/end")
async def end_session(req: EndSessionRequest):
    """End a workout session and get summary."""
    summary = session_mgr.end_session(req.session_id)
    if summary is None:
        return {"error": "Session not found or already ended"}

    # Generate coaching summary from Gemini
    coaching = await generate_coaching_summary(summary)
    summary["coaching_summary"] = coaching

    # Save to session object and persist to Firestore
    session = session_mgr.get_session(req.session_id)
    if session:
        session.coaching_summary = coaching
        await firestore_client.save_session(session.to_firestore_dict())

    return summary


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get current session state."""
    session = session_mgr.get_session(session_id)
    if session is None:
        return {"error": "Session not found"}
    return {
        "session_id": session.session_id,
        "exercise": session.exercise,
        "total_reps": session.total_reps,
        "duration_seconds": session.duration_seconds,
        "form_score": session.form_score,
        "is_active": session.is_active,
    }


@app.get("/sessions/{user_id}")
async def get_user_sessions(user_id: str):
    """Get workout history for a user from Firestore."""
    sessions = await firestore_client.get_user_sessions(user_id)
    return {"sessions": sessions}


# --- Workout Planning APIs ---

@app.post("/workout/generate")
async def generate_workout_endpoint(req: GenerateWorkoutRequest):
    """Generate a workout plan from check-in data."""
    checkin = CheckInData(
        goal=req.goal,
        time_minutes=req.time_minutes,
        equipment=req.equipment,
        energy=req.energy,
        soreness=req.soreness,
        target_muscles=req.target_muscles,
        level=req.level,
        crowded_gym=req.crowded_gym,
        low_confidence=req.low_confidence,
        user_context=req.user_context,
    )
    plan = await generate_workout(checkin)
    return plan.to_dict()


@app.post("/workout/generate_scan")
async def generate_workout_scan_endpoint(
    checkin_data: str = Form(...),
    images: list[UploadFile] = File(...)
):
    """Generate a workout using checkin data and an environment scan gallery."""
    try:
        data_dict = json.loads(checkin_data)
        checkin = CheckInData(
            goal=data_dict.get("goal", "general"),
            time_minutes=data_dict.get("time_minutes", 25),
            equipment=data_dict.get("equipment", "none"),
            energy=data_dict.get("energy", "medium"),
            soreness=data_dict.get("soreness", []),
            target_muscles=data_dict.get("target_muscles", []),
            level=data_dict.get("level", "beginner"),
            crowded_gym=data_dict.get("crowded_gym", False),
            low_confidence=data_dict.get("low_confidence", False),
            user_context=data_dict.get("user_context", "")
        )
        
        # Save images temporarily
        image_paths = []
        for i, img in enumerate(images):
            path = f"/tmp/scan_frame_{i}.jpg"
            with open(path, "wb") as f:
                f.write(await img.read())
            image_paths.append(path)
            
        plan = await generate_workout(checkin, image_paths)
        
        # cleanup
        for path in image_paths:
            try:
                os.remove(path)
            except Exception:
                pass
            
        return plan.to_dict()
    except Exception as e:
        logging.error(f"Scan Generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/workout/adapt")
async def adapt_exercise_endpoint(req: AdaptExerciseRequest):
    """Suggest a replacement exercise."""
    result = await adapt_exercise(
        current_exercise=req.exercise,
        reason=req.reason,
        context=req.session_context,
    )
    return result


@app.post("/workout/warmup")
async def generate_warmup_endpoint(req: WarmupRequest):
    """Generate warmup moves based on planned exercises."""
    exercises = [
        ExercisePlan(
            exercise=e.exercise,
            sets=3,
            reps=10,
            cue="",
        )
        for e in req.exercises
    ]
    warmup = await generate_warmup(exercises)
    return {"warmup": warmup}


@app.post("/workout/rescue")
async def rescue_workout(req: RescueRequest):
    """Rescue: adapt current exercise based on friction reason."""
    result = await adapt_exercise(
        current_exercise=req.exercise,
        reason=req.reason,
        context=req.session_context,
    )
    return result


# --- Profile APIs ---

@app.post("/profile/save")
async def save_profile(req: SaveProfileRequest):
    """Save anonymous user profile to Firestore."""
    from backend.user_profile import UserProfile
    profile = UserProfile(
        user_id=req.user_id,
        level=req.level,
        preferred_goal=req.preferred_goal,
        preferred_equipment=req.preferred_equipment,
        crowded_gym=req.crowded_gym,
        low_confidence=req.low_confidence,
    )
    await firestore_client.save_session(profile.to_dict())  # reuse sessions collection for now
    return {"status": "ok"}


@app.get("/profile/{user_id}")
async def get_profile(user_id: str):
    """Get anonymous user profile."""
    data = await firestore_client.get_session(user_id)
    if data:
        return data
    return {"user_id": user_id, "level": "beginner", "session_count": 0}


# --- WebSocket: Gemini bidi-streaming ---

@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str, session_id: str):
    """
    ADK bidi-streaming WebSocket endpoint.

    Browser sends:
      - binary frames: raw PCM audio (16-bit, 16kHz, mono)
      - text frames: JSON {"type": "text"|"image"|"pose_event", ...}

    Server sends back:
      - ADK events as JSON (audio in content.parts[].inlineData)
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: user={user_id} session={session_id}")

    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["TEXT"],
    )

    # Get or create ADK session
    adk_session = await adk_session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if not adk_session:
        adk_session = await adk_session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )

    live_request_queue = LiveRequestQueue()

    # Find active workout session for this user (if any)
    workout_session = None
    for s in session_mgr.get_active_sessions():
        if s.user_id == user_id:
            workout_session = s
            break

    async def upstream_task():
        nonlocal workout_session
        try:
            while True:
                message = await websocket.receive()

                # Handle disconnect message
                if message.get("type") == "websocket.disconnect":
                    break

                if "bytes" in message:
                    audio_blob = types.Blob(
                        mime_type="audio/pcm;rate=16000",
                        data=message["bytes"],
                    )
                    live_request_queue.send_realtime(audio_blob)

                elif "text" in message:
                    msg = json.loads(message["text"])
                    msg_type = msg.get("type")

                    if msg_type == "text":
                        # Enrich text with session context if available
                        text = msg["data"]
                        if workout_session and workout_session.is_active:
                            text = f"[SESSION: {workout_session.context_for_agent()}]\n{text}"
                        content = types.Content(
                            parts=[types.Part(text=text)]
                        )
                        live_request_queue.send_content(content)

                    elif msg_type == "image":
                        image_data = base64.b64decode(msg["data"])
                        blob = types.Blob(
                            mime_type=msg.get("mimeType", "image/jpeg"),
                            data=image_data,
                        )
                        live_request_queue.send_realtime(blob)

                    elif msg_type == "pose_event":
                        data = msg["data"]

                        # Record rep in workout session
                        if workout_session and workout_session.is_active and data.get("rep", 0) > workout_session.total_reps:
                            form_quality = data.get("form_issue") or "good"
                            workout_session.add_rep(form_quality)

                        # Enrich with session context
                        event_text = json.dumps(data)
                        if workout_session and workout_session.is_active:
                            event_text = f"[SESSION: {workout_session.context_for_agent()}] [POSE EVENT] {event_text}"
                        else:
                            event_text = f"[POSE EVENT] {event_text}"

                        content = types.Content(
                            parts=[types.Part(text=event_text)]
                        )
                        live_request_queue.send_content(content)

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Upstream error: {e}")

    async def downstream_task():
        try:
            async for event in runner.run_live(
                user_id=user_id,
                session_id=session_id,
                live_request_queue=live_request_queue,
                run_config=run_config,
            ):
                try:
                    await websocket.send_text(
                        event.model_dump_json(exclude_none=True, by_alias=True)
                    )
                except Exception:
                    break
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Downstream error: {e}")

    try:
        await asyncio.gather(upstream_task(), downstream_task())
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Session error: {e}")
        try:
            await websocket.close(code=1011, reason=str(e)[:120])
        except Exception:
            pass
    finally:
        live_request_queue.close()
        logger.info(f"WebSocket closed: {session_id}")


# --- Serve frontend ---

app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/test")
async def test_page():
    return FileResponse("frontend/test.html")


@app.get("/wstest")
async def wstest_page():
    return FileResponse("frontend/wstest.html")


@app.get("/")
async def index():
    return FileResponse("frontend/index.html")
