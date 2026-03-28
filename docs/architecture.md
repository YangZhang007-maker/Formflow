# RepWise Architecture

## System Diagram

```
        Camera + Microphone
              |
              v
    +-------------------+
    |   Web Browser      |
    |                   |
    | MediaPipe Pose ---|---> Joint angles, rep counting, form detection
    |   (in-browser)    |
    |                   |
    +--------+----------+
             |
      WebSocket + REST
             |
             v
    +-------------------+        +-------------------+
    |  FastAPI Backend   |------->|  Gemini 2.5 Flash  |
    |  (Cloud Run)      |<-------|  Native Audio      |
    |                   |        |  (bidi-streaming)  |
    |  - Session APIs   |        +-------------------+
    |  - ADK Runner     |
    |  - WebSocket proxy|
    +--------+----------+
             |
             v
    +-------------------+
    |  Cloud Firestore   |
    |  (sessions)       |
    +-------------------+
```

## Data Flow

1. Browser captures camera + mic
2. MediaPipe detects pose landmarks in-browser (10fps)
3. RepCounter computes joint angles, counts reps, detects form issues
4. Audio streams to backend via WebSocket (binary PCM 16kHz)
5. Video frames sent as base64 JPEG every 2s
6. Pose events (rep count + form issues) sent as JSON, throttled to 1/4s
7. Backend proxies all to Gemini via ADK LiveRequestQueue
8. Gemini responds with voice coaching (PCM 24kHz)
9. Session data persisted to Firestore

## Key Design Decisions

- **Gemini handles speech**: No separate STT/TTS — Gemini Live API does it all
- **Pose detection in browser**: Keeps backend simple, reduces latency
- **ADK over raw SDK**: Session management, reconnection, event lifecycle handled by framework
- **URL-safe base64**: ADK/Pydantic serializes audio as URL-safe b64, frontend converts before atob()
- **Throttled pose events**: Max 1 per 4s to avoid queuing Gemini responses
- **Audio chunk batching**: Up to 5 chunks merged before playback to reduce scheduling overhead

## Firestore Schema

Collection: `sessions`

```json
{
  "session_id": "string",
  "user_id": "string",
  "exercise": "squat|pushup|plank",
  "start_time": "ISO timestamp",
  "end_time": "ISO timestamp",
  "total_reps": 10,
  "duration_seconds": 28,
  "form_score": 7.5,
  "rep_events": [
    {"rep": 1, "timestamp": "ISO", "form_quality": "good"},
    {"rep": 2, "timestamp": "ISO", "form_quality": "leaning_forward"}
  ],
  "coaching_summary": "string (Gemini-generated)"
}
```
