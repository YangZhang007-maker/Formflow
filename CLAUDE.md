# RepWise - Live AI Workout Coach

## Project
Gemini Live Agent Challenge submission. Real-time AI gym coach using Gemini Live API + MediaPipe pose detection.

## Commands
- Run backend: `cd /Users/sujnesh/repwise && source .venv/bin/activate && uvicorn backend.main:app --reload --port 8080`
- Run tests: `cd /Users/sujnesh/repwise && source .venv/bin/activate && pytest tests/ -v`
- Docker build: `docker build -t repwise .`
- Deploy: `gcloud run deploy repwise --source . --region us-central1`

## Architecture
- **Frontend**: Plain HTML/JS, camera + MediaPipe pose (in-browser), WebSocket to backend
- **Backend**: Python FastAPI + ADK bidi-streaming → Gemini 2.5 Flash native audio
- **Persistence**: Firestore (sessions collection)
- **Deploy**: Cloud Run

## Key Files
- `backend/main.py` — FastAPI server, WebSocket proxy, session APIs
- `backend/agent.py` — ADK Agent definition
- `backend/sessions.py` — Session management logic
- `backend/config.py` — Model config, system prompt
- `frontend/app.js` — Camera, WebSocket, audio playback
- `frontend/pose.js` — MediaPipe pose detection, RepCounter

## Testing
- `pytest tests/ -v` for all tests
- Tests cover: session lifecycle, rep tracking, summary generation
