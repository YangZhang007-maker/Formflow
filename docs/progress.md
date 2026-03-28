# RepWise Progress

## Phase 0 — Foundation (Complete)
- ✅ Camera feed with pose detection (MediaPipe in-browser)
- ✅ Rep counting (squats, push-ups, plank) with idle state + visibility checks
- ✅ Form feedback (persistent pill overlay, 3s display)
- ✅ Gemini Live API connection via ADK bidi-streaming
- ✅ Voice output working (URL-safe base64 fix)
- ✅ Audio chunk batching + queue cap for reduced lag
- ✅ Pose event throttling (1 per 4s)
- ✅ Mobile-optimized UI with dark theme
- ✅ Ngrok HTTPS tunnel for mobile testing
- ✅ Basic Firestore workout save (POST /api/workout)

## Phase 1 — Backend Session APIs + Tests (Complete)
- ✅ Session management (start/rep/end) with SessionManager + WorkoutSession
- ✅ pytest setup (36 tests passing)
- ✅ Session lifecycle tests (create, get, end, double-end)
- ✅ Rep tracking tests (add, form quality, invalid session)
- ✅ Summary generation tests (form score, issues, duration)
- ✅ REST API tests (FastAPI TestClient)
- ✅ Frontend wired to session APIs (start/rep/end)
- ✅ Renamed to RepWise throughout
- ✅ Agent context enrichment (session data injected into Gemini prompts)

## Phase 2 — Firestore Persistence (Complete)
- ✅ Dedicated firestore_client.py with lazy init
- ✅ Session CRUD operations (save, get, get_user_sessions)
- ✅ Firestore tests with mocked client (6 tests)
- ✅ Sessions saved on workout end with full schema

## Phase 3 — Agent Context Enrichment (Complete)
- ✅ Session context injected into every Gemini message
- ✅ Context includes: reps, form score, duration, issues
- ✅ Enhanced system prompt for context-aware responses
- ✅ Agent can answer "how many reps?" from session data

## Phase 4 — Voice Interaction (Complete)
- ✅ Bidi-streaming voice via ADK WebSocket
- ✅ Interrupt handling (clearAudioQueue on interrupted event)
- ✅ URL-safe base64 audio decoding fix
- ✅ Audio chunk batching + queue cap for low latency

## Phase 5 — Post-Workout Summary (Complete)
- ✅ Gemini-generated coaching debrief
- ✅ Fallback summary when Gemini unavailable
- ✅ Summary tests (6 tests)
- ✅ Coaching summary displayed in workout complete UI
- ✅ Form score + issues shown in summary card

## Phase 6 — Cloud Deployment (Complete)
- ✅ Cloud Run deployed: https://repwise-384586125133.us-central1.run.app
- ✅ Firestore Native database created (us-central1, free tier)
- ✅ Billing linked, APIs enabled
- ✅ Production HTTPS — camera/mic works on mobile without ngrok
- [ ] Demo video
- [ ] Devpost submission

## Phase A — Anonymous Profile + Setup (Complete)
- ✅ Anonymous user ID generation (rw_xxxxxxxxxxxx)
- ✅ UserProfile dataclass with level, preferences, prior issues
- ✅ Profile persistence via Firestore
- ✅ Profile context injection for workout generation
- ✅ 10 profile tests passing

## Phase B — Level + Goal-based Mission Generation (Complete)
- ✅ Beginner vs intermediate branching in workout generation
- ✅ Beginner capped at 3 exercises, lower volume
- ✅ Low confidence mode simplifies further
- ✅ Crowded gym mode in prompts
- ✅ Quick session goal support
- ✅ Rescue endpoint with 6 reason types
- ✅ Fallback rescue logic per reason (equipment_busy, low_energy, discomfort, etc.)
- ✅ Profile save/get endpoints
- ✅ 24 new tests (95 total) all passing
- ✅ Luxury athletic UI with Bebas Neue + DM Sans + warm amber palette

## Phase C — Live Coach Mode Restructure (Complete)
- ✅ Mission-based flow: "Generate My Mission" → "Today's Mission" → "Mission Complete"
- ✅ Level selection (Beginner/Intermediate) in check-in
- ✅ Crowded Gym + Low Confidence context toggles
- ✅ Coach Online / Going live status copy
- ✅ Rescue button replaces Swap in workout controls

## Phase D — Workout Rescue (Complete)
- ✅ Rescue modal with 6 friction reasons
- ✅ Equipment Busy, Low Energy, Short on Time, Discomfort, Don't Know, Easier
- ✅ POST /workout/rescue endpoint
- ✅ Real-time exercise update after rescue
- ✅ Gemini notified of rescue for voice coaching

## Phase E — Mission Complete (Complete)
- ✅ Badges: Session Complete, Clean Form (8+), Endurance (20+ min), Rep Machine (50+ reps)
- ✅ Badge animations (scale-in)
- ✅ Coaching debrief from Gemini
- ✅ "New Workout" restarts full flow

## Phase F — Rescue Hero + State Flow + Polish (Complete)
- ✅ Rescue button is now hero-sized, full-width, accent-bordered, with icon
- ✅ Rescue flash animation on success ("Rescued!" → green flash → revert)
- ✅ State-based flow: data-state on #app controls panel visibility with CSS
- ✅ Four clean states: setup → mission → live → complete
- ✅ Mission personalization tags: level, goal, time, equipment, crowded gym, confidence mode
- ✅ Header tag updates per state: "Coach Online" → "Mission Ready" → "Live Session" → "Complete"
- ✅ Rescue count tracked, "Rescue Recovery" badge on Mission Complete
- ✅ Context section consolidated (soreness + crowded + confidence in one group)
- ✅ Goal labels updated: "Build Muscle", "Lose Fat", "Quick Session"
- ✅ Level moved to top of check-in (most important decision)
- ✅ "End Mission" label on stop button
- ✅ "Start Mission" / "New Mission" copy throughout

## Session Engine Fixes (Complete)
- ✅ ExerciseState class: tracks sets, reps per set, completion, form issues
- ✅ Reps reset per set (Set 1 of 3 / 8 of 12 reps)
- ✅ Set auto-advances when target reps reached
- ✅ Exercise complete stops accepting reps
- ✅ initExercise() single function for start/next/rescue — full state reset
- ✅ Rescue fully resets: timer, reps, sets, pose detector, fatigue flag
- ✅ Timer shows per-exercise time (not total workout)
- ✅ Audio context never closed during workout (only on actual end)
- ✅ AudioContext not recreated without user gesture
- ✅ intentionalClose flag prevents false "Disconnected" on normal end
- ✅ Auto-reconnect WebSocket after 3s if unintentional disconnect
- ✅ Mission Complete grounded in exerciseHistory (per-exercise breakdown)
- ✅ Summary shows actual sets/reps per exercise, rescued exercises marked
- ✅ 12 new exercise state tests (107 total passing)

## Audio + State Machine + Rest Timer (Complete)
- ✅ Audio robustness: try/catch around decode+playback, isPlaying reset on error, never create AudioContext outside user gesture
- ✅ sessionPhase guard: reps blocked during "resting" and "exerciseComplete" phases
- ✅ Rest timer: countdown overlay after set completion, auto-starts next set at 0, "Start Next Set" skip button
- ✅ Rest duration heuristic: beginner 45-60s, intermediate strength 90s, quick 20s
- ✅ Rest clears on rescue, next exercise, end workout
- ✅ initExercise() resets sessionPhase, clears rest interval and overlay
- ✅ Timer resets per set after rest ends
- ✅ 4 new rest state tests (111 total passing)
