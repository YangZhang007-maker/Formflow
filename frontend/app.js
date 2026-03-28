/**
 * Formflow App — AI Workout Partner
 * Flow: Setup → Mission → Live Session → Complete
 */
import { initPose, detectPose, RepCounter } from "./pose.js";

// ============================================================
// Exercise State Model (mirrors test_exercise_state.py)
// ============================================================
class ExerciseState {
    constructor(exercise, targetSets, targetReps, isTimed = false) {
        this.exercise = exercise;
        this.targetSets = targetSets;
        this.targetReps = targetReps;
        this.isTimed = isTimed;
        this.currentSet = 1;
        this.repsInSet = 0;
        this.completedSets = 0;
        this.totalReps = 0;
        this.formIssues = [];
    }

    addRep(formQuality = "good") {
        const result = { setComplete: false, exerciseComplete: false };
        if (this.completedSets >= this.targetSets) {
            result.exerciseComplete = true;
            return result;
        }
        this.repsInSet++;
        this.totalReps++;
        if (formQuality !== "good") this.formIssues.push(formQuality);

        if (this.repsInSet >= this.targetReps) {
            this.completedSets++;
            result.setComplete = true;
            if (this.completedSets >= this.targetSets) {
                result.exerciseComplete = true;
            } else {
                this.currentSet++;
                this.repsInSet = 0;
            }
        }
        return result;
    }

    toSummary() {
        return {
            exercise: this.exercise,
            setsCompleted: this.completedSets,
            totalReps: this.totalReps,
            formIssues: [...new Set(this.formIssues)],
        };
    }
}

// ============================================================
// State
// ============================================================
let workoutPlan = null;
let currentExerciseIdx = 0;
let exerciseState = null;       // ExerciseState instance
let exerciseHistory = [];       // Array of exercise summaries for grounded Mission Complete
let sessionPhase = "active";    // "active" | "resting" | "exerciseComplete"
let restInterval = null;        // Rest countdown timer
let restSecondsLeft = 0;
let ws = null;
let intentionalClose = false;   // Prevents false "Disconnected" on normal end
let mediaStream = null;
let repCounter = null;
let audioProcessor = null; // kept for cleanup only
let poseInterval = null;
let videoSendInterval = null;
let timerInterval = null;
let workoutStartTime = null;
let exerciseStartTime = null;   // Per-exercise timer
let fatigueWarned = false;
let feedbackTimeout = null;
let lastPoseEventTime = 0;
let lastFormIssue = null;
let goodFormCounter = 0;
let totalScore = 0;
// Audio removed — coach communicates via text transcript
const userId = localStorage.getItem("formflow_uid") || "user_" + Math.random().toString(36).slice(2, 8);
localStorage.setItem("formflow_uid", userId);
let sessionId = null; // Generated fresh per workout
let rescueCount = 0;
let checkinData = null;

// State machine
function setState(state) {
    document.getElementById("app").dataset.state = state;
    const tag = document.getElementById("header-tag");
    if (tag) {
        const labels = { setup: "Coach Online", mission: "Mission Ready", live: "Live Session", complete: "Complete" };
        tag.textContent = labels[state] || "";
        tag.style.color = state === "live" ? "var(--success)" : "var(--text-dim)";
        tag.style.background = state === "live" ? "rgba(92,184,92,0.1)" : "var(--surface)";
    }
}

// ============================================================
// DOM
// ============================================================
const btnNextScan = document.getElementById("btn-next-scan");
const btnSkipScan = document.getElementById("btn-skip-scan");
const btnStartScan = document.getElementById("btn-start-scan");
const scanTimer = document.getElementById("scan-timer");
const envCamera = document.getElementById("env-camera");
const startWorkoutBtn = document.getElementById("start-workout-btn");
const nextExerciseBtn = document.getElementById("next-exercise-btn");
const rescueBtn = document.getElementById("rescue-btn");
const rescueModal = document.getElementById("rescue-modal");
const rescueCancel = document.getElementById("rescue-cancel");
const stopBtn = document.getElementById("stop-btn");
const newWorkoutBtn = document.getElementById("new-workout-btn");
const progressFill = document.getElementById("progress-fill");
const progressText = document.getElementById("progress-text");
const exerciseCue = document.getElementById("exercise-cue");
const repLabel = document.getElementById("rep-label");
const camera = document.getElementById("camera");
const poseCanvas = document.getElementById("pose-canvas");
const repCountEl = document.getElementById("rep-count");
const exerciseBadge = document.getElementById("exercise-badge");
const timerEl = document.getElementById("timer");
const statusDot = document.getElementById("connection-status");
const statusTextEl = document.getElementById("status-text");
const feedbackPill = document.getElementById("form-feedback");
const feedbackIcon = document.getElementById("feedback-icon");
const feedbackText = document.getElementById("feedback-text");
const messagesList = document.getElementById("messages-list");
const summaryStats = document.getElementById("summary-stats");
const currentExerciseName = document.getElementById("current-exercise-name");
const currentExerciseTarget = document.getElementById("current-exercise-target");
const nextExerciseName = document.getElementById("next-exercise-name");
const hudScore = document.getElementById("hud-score");
const hudCombo = document.getElementById("hud-combo");
const floatingContainer = document.getElementById("floating-feedback-container");

// ============================================================
// Helpers
// ============================================================
function updateScoreDisplay(combo) {
    if (hudScore) hudScore.textContent = totalScore;
    if (hudCombo) {
        hudCombo.textContent = `x${combo || 0}`;
        hudCombo.classList.add("active");
        setTimeout(() => hudCombo.classList.remove("active"), 300);
    }
}

function popFloatingReward(text, isPerfect) {
    if (!floatingContainer) return;
    const el = document.createElement("div");
    el.className = `floating-reward${isPerfect ? " perfect" : ""}`;
    el.textContent = text;
    floatingContainer.appendChild(el);
    setTimeout(() => {
        if (floatingContainer.contains(el)) el.remove();
    }, 1200);
}

// ============================================================
// STEP 1: Check-in
// ============================================================
document.querySelectorAll(".chip-group").forEach(group => {
    const isMulti = group.classList.contains("multi");
    group.querySelectorAll(".chip").forEach(chip => {
        chip.addEventListener("click", () => {
            if (isMulti) { chip.classList.toggle("selected"); }
            else { group.querySelectorAll(".chip").forEach(c => c.classList.remove("selected")); chip.classList.add("selected"); }
        });
    });
});

function getCheckinData() {
    const getSelected = (field) => {
        const group = document.querySelector(`.chip-group[data-field="${field}"]`);
        const selected = group.querySelector(".chip.selected");
        return selected ? selected.dataset.value : null;
    };
    const getMultiSelected = (field) => {
        const group = document.querySelector(`.chip-group[data-field="${field}"]`);
        return Array.from(group.querySelectorAll(".chip.selected")).map(c => c.dataset.value);
    };
    const userContextText = document.getElementById("user-context-text") ? document.getElementById("user-context-text").value.trim() : "";
    return {
        goal: getSelected("goal") || "general",
        time_minutes: parseInt(getSelected("time") || "25"),
        equipment: getSelected("equipment") || "none",
        energy: getSelected("energy") || "medium",
        soreness: getMultiSelected("soreness"),
        target_muscles: getMultiSelected("target_muscles"),
        level: getSelected("level") || "beginner",
        crowded_gym: getMultiSelected("crowded_gym").length > 0,
        low_confidence: getMultiSelected("low_confidence").length > 0,
        user_context: userContextText
    };
}

let envStream = null;
let envRecorder = null;
let envChunks = [];

function setStateAttribute(state) {
    document.getElementById("app").setAttribute("data-state", state);
}

btnNextScan.addEventListener("click", async () => {
    setStateAttribute("scan");
    try {
        envStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
        envCamera.srcObject = envStream;
    } catch (e) {
        console.error("Camera access denied", e);
    }
});

btnSkipScan.addEventListener("click", () => {
    if (envStream) {
        envStream.getTracks().forEach(t => t.stop());
        envStream = null;
    }
    if (envCamera) envCamera.srcObject = null;
    generateMission(null);
});

btnStartScan.addEventListener("click", () => {
    if (!envStream) return;
    btnStartScan.disabled = true;
    btnStartScan.querySelector(".btn-text").innerHTML = '<span class="loading"></span>Scanning...';
    btnSkipScan.style.display = "none";
    
    const snapshots = [];
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    
    // Setup capture dimensions
    canvas.width = 640;
    canvas.height = 480;
    
    scanTimer.style.display = 'block';
    scanTimer.textContent = '8';
    let remaining = 8;
    
    // Capture first frame immediately
    ctx.drawImage(envCamera, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => snapshots.push(blob), "image/jpeg", 0.7);

    const tick = setInterval(() => {
        remaining--;
        scanTimer.textContent = remaining;
        
        // Capture a frame every second
        ctx.drawImage(envCamera, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => snapshots.push(blob), "image/jpeg", 0.7);

        if (remaining <= 0) {
            clearInterval(tick);
            // Stop camera
            if (envStream) {
                envStream.getTracks().forEach(t => t.stop());
                envStream = null;
            }
            if (envCamera) {
                envCamera.srcObject = null;
                envCamera.load();
            }
            
            // Wait a moment for the last blob to fulfill, then send
            setTimeout(() => {
                generateMissionFromSnapshots(snapshots);
            }, 500);
        }
    }, 1000);
});

async function generateMissionFromSnapshots(snapshots) {
    btnNextScan.disabled = true;
    btnSkipScan.disabled = true;
    btnStartScan.disabled = true;
    
    btnStartScan.querySelector(".btn-text").innerHTML = '<span class="loading"></span>[Stage 1/2] Analyzing Vision...';
    
    try {
        const checkin = getCheckinData();
        checkinData = checkin;
        
        const formData = new FormData();
        formData.append("checkin_data", JSON.stringify(checkin));
        
        // Add all image snapshots
        snapshots.forEach((blob, i) => {
            formData.append("images", blob, `frame_${i}.jpg`);
        });
        
        const resp = await fetch("/workout/generate_scan", {
            method: "POST",
            body: formData
        });
        
        // Update message for stage 2
        btnStartScan.querySelector(".btn-text").innerHTML = '<span class="loading"></span>[Stage 2/2] Generating Mission...';
        
        workoutPlan = await resp.json();
        console.log("Final Plan Received:", workoutPlan);
        showPlan();
    } catch (err) {
        console.error("Scan error:", err);
        btnStartScan.disabled = false;
        btnStartScan.querySelector(".btn-text").textContent = "Error. Try Again";
        btnSkipScan.style.display = "block";
        btnSkipScan.disabled = false;
    }
}

async function generateMission(videoBlob) {
    // This is now only used for the "Skip Scan" case (where videoBlob is null)
    btnNextScan.disabled = true;
    btnSkipScan.disabled = true;
    btnStartScan.disabled = true;
    
    btnSkipScan.innerHTML = '<span class="loading"></span>Planning Mission...';
    
    try {
        const checkin = getCheckinData();
        checkinData = checkin;
        
        const resp = await fetch("/workout/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(checkin),
        });
        
        workoutPlan = await resp.json();
        console.log("Final Plan Received:", workoutPlan);
        showPlan();
    } catch (err) {
        console.error("Mission error:", err);
        btnSkipScan.innerHTML = 'Skip Scan, Generate Mission';
        btnSkipScan.disabled = false;
        btnStartScan.disabled = false;
    }
}

// ============================================================
// STEP 2: Show Plan
// ============================================================
function showPlan() {
    setState("mission");

    // Mission tags
    const tagsEl = document.getElementById("mission-tags");
    if (tagsEl && checkinData) {
        const tags = [];
        tags.push({ text: checkinData.level === "beginner" ? "Beginner-Friendly" : "Intermediate", highlight: true });
        const goalLabels = { strength: "Build Muscle", endurance: "Lose Fat", general: "General", quick: "Quick Win", flexibility: "Flexibility" };
        tags.push({ text: goalLabels[checkinData.goal] || checkinData.goal });
        tags.push({ text: `${checkinData.time_minutes} min` });
        const equipLabels = { none: "Bodyweight", dumbbells: "Dumbbells", full_gym: "Full Gym", minimal: "Minimal Kit" };
        tags.push({ text: equipLabels[checkinData.equipment] || checkinData.equipment });
        if (checkinData.crowded_gym) tags.push({ text: "Crowded Gym", highlight: true });
        if (checkinData.low_confidence) tags.push({ text: "Confidence Mode", highlight: true });
        if (checkinData.target_muscles && checkinData.target_muscles.length > 0) {
            const muscles = checkinData.target_muscles.map(m => m.charAt(0).toUpperCase() + m.slice(1)).join(", ");
            tags.push({ text: "Focus: " + muscles, highlight: true });
        }
        if (checkinData.energy === "low") tags.push({ text: "Low Energy" });
        if (checkinData.energy === "high") tags.push({ text: "High Energy" });
        tagsEl.innerHTML = tags.map(t => `<span class="mission-tag${t.highlight ? ' highlight' : ''}">${t.text}</span>`).join("");
    }

    const warmupSection = document.getElementById("warmup-section");
    const warmupList = document.getElementById("warmup-list");
    if (workoutPlan.warmup && workoutPlan.warmup.length > 0) {
        warmupSection.classList.remove("hidden");
        warmupList.innerHTML = workoutPlan.warmup.map(w => `<li>${w}</li>`).join("");
    }

    const exerciseList = document.getElementById("exercise-list");
    exerciseList.innerHTML = workoutPlan.exercises.map((ex, i) => {
        const meta = ex.is_timed
            ? `${ex.sets} sets \u00d7 ${ex.reps || ex.duration_seconds}s`
            : `${ex.sets} sets \u00d7 ${ex.reps} reps`;
        const cue = ex.cue ? `<div class="ex-cue">${ex.cue}</div>` : "";
        return `<div class="ex-card"><div class="ex-num">${i + 1}</div><div class="ex-details"><div class="ex-name">${ex.exercise}</div><div class="ex-meta">${meta}</div>${cue}</div></div>`;
    }).join("");

    const planMeta = document.getElementById("plan-meta");
    planMeta.textContent = `~${workoutPlan.estimated_minutes} min \u00b7 ${workoutPlan.focus}`;

    // Show environment scan result banner
    const envBanner = document.getElementById("env-scan-banner");
    const envResultText = document.getElementById("env-scan-result-text");
    if (envBanner && envResultText && workoutPlan.env_scan_result) {
        envResultText.textContent = workoutPlan.env_scan_result;
        envBanner.classList.remove("hidden");
    } else if (envBanner) {
        envBanner.classList.add("hidden");
    }
}

startWorkoutBtn.addEventListener("click", () => startWorkout());

// ============================================================
// STEP 3: Active Workout
// ============================================================

// Rest duration heuristic (mirrors test_exercise_state.py)
function getRestDuration() {
    if (!checkinData) return 45;
    if (checkinData.goal === "quick") return 20;
    if (checkinData.level === "beginner") return checkinData.goal === "strength" ? 60 : 45;
    return checkinData.goal === "strength" ? 90 : 60;
}

function startRest() {
    sessionPhase = "resting";
    restSecondsLeft = getRestDuration();
    const overlay = document.getElementById("rest-overlay");
    const countdown = document.getElementById("rest-countdown");
    const sub = document.getElementById("rest-sub");
    if (overlay) overlay.classList.remove("hidden");
    if (countdown) countdown.textContent = restSecondsLeft;
    if (sub && exerciseState) {
        sub.textContent = `Next: Set ${exerciseState.currentSet}`;
    }

    restInterval = setInterval(() => {
        restSecondsLeft--;
        if (countdown) countdown.textContent = Math.max(0, restSecondsLeft);
        if (restSecondsLeft <= 0) {
            endRest();
        }
    }, 1000);
}

function endRest() {
    if (restInterval) { clearInterval(restInterval); restInterval = null; }
    const overlay = document.getElementById("rest-overlay");
    if (overlay) overlay.classList.add("hidden");
    sessionPhase = "active";
    exerciseStartTime = Date.now(); // reset exercise timer for new set
    addCoachMessage(`Set ${exerciseState.currentSet} — let's go!`);
}

// Initialize exercise state — called on start, next, and rescue
function initExercise(ex) {
    // Clear any active rest
    if (restInterval) { clearInterval(restInterval); restInterval = null; }
    const restOverlay = document.getElementById("rest-overlay");
    if (restOverlay) restOverlay.classList.add("hidden");
    sessionPhase = "active";

    const exerciseName = mapExerciseToInternal(ex.exercise);
    repCounter = new RepCounter(exerciseName);
    exerciseState = new ExerciseState(ex.exercise, ex.sets, ex.reps || 30, ex.is_timed || false);
    exerciseStartTime = Date.now();
    fatigueWarned = false;
    lastFormIssue = null;
    goodFormCounter = 0;

    // Update UI
    exerciseBadge.textContent = ex.exercise.toUpperCase();
    repCountEl.textContent = "0";
    repLabel.textContent = ex.is_timed ? "seconds" : `/ ${ex.reps} reps`;
    updateExerciseInfoBar();
    updateSetDisplay();
    hideFeedback();
}

function updateSetDisplay() {
    if (!exerciseState) return;
    const setInfo = `Set ${exerciseState.currentSet} of ${exerciseState.targetSets}`;
    currentExerciseTarget.textContent = setInfo;
    repCountEl.textContent = exerciseState.repsInSet;
    repLabel.textContent = exerciseState.isTimed
        ? "seconds"
        : `/ ${exerciseState.targetReps}`;
    
    const setCountEl = document.getElementById("set-count");
    if (setCountEl) setCountEl.textContent = `${exerciseState.currentSet}/${exerciseState.targetSets}`;
}

async function startWorkout() {
    rescueCount = 0;
    exerciseHistory = [];
    messagesList.innerHTML = "";
    currentExerciseIdx = 0;
    workoutStartTime = Date.now();
    intentionalClose = false;
    _geminiReady = false;
    totalScore = 0;
    updateScoreDisplay(0);
    // Fresh session ID per workout — prevents ADK session conflicts
    sessionId = "s_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6);
 
    if (!workoutPlan || !workoutPlan.exercises || workoutPlan.exercises.length === 0) {
        addCoachMessage("Error: Plan generated but exercises are missing. Please try skipping scan.");
        return;
    }

    initExercise(workoutPlan.exercises[0]);
    timerEl.textContent = "0:00";

    // Wire skip-rest button
    const skipRestBtn = document.getElementById("skip-rest-btn");
    if (skipRestBtn) skipRestBtn.onclick = () => endRest();

    // Backend session
    try {
        const resp = await fetch("/session/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: userId, exercise: mapExerciseToInternal(workoutPlan.exercises[0].exercise) }),
        });
        const data = await resp.json();
        window._workoutSessionId = data.session_id;
    } catch (err) {
        console.warn("Failed to start session:", err);
    }

    // Audio removed — coach uses text transcript

    // Camera FIRST — must complete before WebSocket on mobile Safari
    // Give OS plenty of time to release camera from previous scan session
    setState("live");
    await new Promise(r => setTimeout(r, 800));

    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "user", width: 640, height: 480 },
            audio: true,
        });
        camera.srcObject = mediaStream;
        await camera.play();
        poseCanvas.width = camera.videoWidth || 640;
        poseCanvas.height = camera.videoHeight || 480;

        // Pose detection (non-blocking)
        initPose(poseCanvas).then(() => {
            poseInterval = setInterval(processPoseFrame, 100);
        }).catch(err => {
            console.warn("Pose detection failed:", err);
            addCoachMessage("Pose detection unavailable — voice coaching active.");
        });
    } catch (err) {
        addCoachMessage("Camera/mic unavailable — voice-only coaching active.");
    }

    // WebSocket AFTER camera is fully initialized
    try {
        connectWebSocket();
    } catch (err) {
        addCoachMessage("Coach connection failed: " + err.message);
    }
}

function mapExerciseToInternal(name) {
    const lower = name.toLowerCase();
    if (lower.includes("squat") || lower.includes("goblet") || lower.includes("leg press") || lower.includes("wall sit")) return "squat";
    if (lower.includes("push") || lower.includes("press") || lower.includes("bench") || lower.includes("fly") || lower.includes("dip")) return "pushup";
    if (lower.includes("plank") || lower.includes("dead bug")) return "plank";
    return "squat";
}

function updateExerciseInfoBar() {
    if (!workoutPlan) return;
    const total = workoutPlan.exercises.length;
    const current = workoutPlan.exercises[currentExerciseIdx];
    const next = workoutPlan.exercises[currentExerciseIdx + 1];

    const pct = ((currentExerciseIdx + 1) / total) * 100;
    progressFill.style.width = `${pct}%`;
    progressText.textContent = `${currentExerciseIdx + 1} / ${total}`;

    if (current) {
        currentExerciseName.textContent = current.exercise;
        if (current.cue) {
            exerciseCue.textContent = current.cue;
            exerciseCue.classList.add("visible");
        } else {
            exerciseCue.classList.remove("visible");
        }
    }

    nextExerciseName.textContent = next ? next.exercise : "Done!";
}

// Next exercise
nextExerciseBtn.addEventListener("click", () => {
    if (!workoutPlan) return;

    // Save current exercise to history
    if (exerciseState) exerciseHistory.push(exerciseState.toSummary());

    currentExerciseIdx++;
    if (currentExerciseIdx >= workoutPlan.exercises.length) {
        endWorkout();
        return;
    }

    const ex = workoutPlan.exercises[currentExerciseIdx];
    initExercise(ex);
    addCoachMessage(`Next up: ${ex.exercise}`);

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: "text",
            data: `User is now starting ${ex.exercise}. Target: ${ex.sets} sets \u00d7 ${ex.reps} reps. Cue: ${ex.cue || "good form"}. Announce briefly.`,
        }));
    }
});

stopBtn.addEventListener("click", endWorkout);

// ============================================================
// Rescue Flow
// ============================================================
rescueBtn.addEventListener("click", () => { rescueModal.classList.remove("hidden"); });
rescueCancel.addEventListener("click", () => { rescueModal.classList.add("hidden"); });

document.querySelectorAll(".rescue-chip").forEach(chip => {
    chip.addEventListener("click", async () => {
        const reason = chip.dataset.reason;
        rescueModal.classList.add("hidden");
        if (!workoutPlan) return;

        // Save partial progress of current exercise
        if (exerciseState) exerciseHistory.push({ ...exerciseState.toSummary(), rescued: true });

        const current = workoutPlan.exercises[currentExerciseIdx];
        rescueBtn.disabled = true;

        try {
            const resp = await fetch("/workout/rescue", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ exercise: current.exercise, reason, session_context: "" }),
            });
            const result = await resp.json();
            if (result.replacement) {
                workoutPlan.exercises[currentExerciseIdx] = {
                    ...current,
                    exercise: result.replacement,
                    reps: result.reps || current.reps,
                    sets: result.sets || current.sets,
                    cue: result.reason || current.cue,
                };
                const ex = workoutPlan.exercises[currentExerciseIdx];

                // FULL RESET — this is the fix
                initExercise(ex);
                rescueCount++;

                const friendlyReasons = {
                    equipment_busy: "equipment was busy",
                    low_energy: "conserving energy",
                    running_out_of_time: "saving time",
                    discomfort: "avoiding discomfort",
                    dont_know: "simpler alternative",
                    easier: "easier variation",
                };
                addCoachMessage(`Rescued! Now: ${ex.exercise} — ${friendlyReasons[reason] || result.reason}`);

                // Flash rescue button
                const rescueSpan = rescueBtn.querySelector("span");
                rescueBtn.classList.add("rescued");
                if (rescueSpan) rescueSpan.textContent = "Rescued!";
                setTimeout(() => {
                    rescueBtn.classList.remove("rescued");
                    if (rescueSpan) rescueSpan.textContent = "Rescue Workout";
                }, 2000);

                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({
                        type: "text",
                        data: `Exercise rescued to ${ex.exercise}. Reason: ${friendlyReasons[reason] || reason}. Announce briefly and encourage.`,
                    }));
                }
            }
        } catch (err) {
            addCoachMessage("Couldn't rescue — try again.");
        }
        rescueBtn.disabled = false;
    });
});

newWorkoutBtn.addEventListener("click", () => {
    // Stop any lingering env camera
    if (envStream) {
        envStream.getTracks().forEach(t => t.stop());
        envStream = null;
    }
    if (envCamera) envCamera.srcObject = null;

    // Reset scan buttons
    btnNextScan.disabled = false;
    btnSkipScan.disabled = false;
    btnSkipScan.style.display = "block";
    btnStartScan.disabled = false;
    btnStartScan.querySelector(".btn-text").textContent = "Start 8s Scan";
    if (scanTimer) { scanTimer.style.display = "none"; scanTimer.textContent = "8"; }

    workoutPlan = null;
    currentExerciseIdx = 0;
    setState("setup");
});

// ============================================================
// WebSocket
// ============================================================
function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/${userId}/${sessionId}`);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
        statusDot.className = "status-dot connected";
        statusTextEl.textContent = "Coach Online";
        const ex = workoutPlan && workoutPlan.exercises ? workoutPlan.exercises[currentExerciseIdx] : null;
        if (ex) {
            ws.send(JSON.stringify({
                type: "text",
                data: `The user is starting a workout. First exercise: ${ex.exercise}, ${ex.sets} sets × ${ex.reps} reps. Cue: ${ex.cue || "good form"}. Greet them briefly.`,
            }));
        }
    };

    ws.onmessage = (event) => {
        try { handleADKEvent(JSON.parse(event.data)); }
        catch (err) { /* ignore parse errors */ }
    };

    ws.onclose = () => {
        if (!intentionalClose) {
            statusDot.className = "status-dot disconnected";
            statusTextEl.textContent = "Reconnecting...";
            setTimeout(() => {
                if (!intentionalClose && document.getElementById("app").dataset.state === "live") {
                    connectWebSocket();
                }
            }, 3000);
        }
    };

    ws.onerror = () => {};
}

// Transcription buffer
let _transcriptBuffer = "";
let _geminiReady = false;

function handleADKEvent(event) {
    // Start video on first Gemini response
    if (!_geminiReady) {
        _geminiReady = true;
        if (mediaStream) {
            videoSendInterval = setInterval(sendVideoFrame, 2000);
        }
    }

    // Text responses (primary coaching UI)
    if (event.content && event.content.parts) {
        for (const part of event.content.parts) {
            if (part.thought) continue;
            if (part.text && !part.thought) {
                addCoachMessage(part.text.trim());
            }
        }
    }

    // Also show transcription if present (fallback)
    if (event.outputTranscription && event.outputTranscription.finished) {
        const fullText = event.outputTranscription.text || _transcriptBuffer;
        if (fullText.trim()) addCoachMessage(fullText.trim());
        _transcriptBuffer = "";
    } else if (event.outputTranscription && event.outputTranscription.text) {
        _transcriptBuffer = event.outputTranscription.text;
    }
}

// Audio capture removed — text-only coach mode

// ============================================================
// Video Frames
// ============================================================
function sendVideoFrame() {
    if (!ws || ws.readyState !== WebSocket.OPEN || !camera.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = 320; canvas.height = 240;
    canvas.getContext("2d").drawImage(camera, 0, 0, 320, 240);
    canvas.toBlob((blob) => {
        if (!blob) return;
        blob.arrayBuffer().then(buf => {
            ws.send(JSON.stringify({ type: "image", data: arrayBufferToBase64(buf), mimeType: "image/jpeg" }));
        });
    }, "image/jpeg", 0.5);
}

// ============================================================
// Pose Detection + Set-Aware Rep Counting
// ============================================================
function processPoseFrame() {
    if (!camera.videoWidth || !exerciseState) return;

    // Don't count reps during rest or after exercise complete
    if (sessionPhase !== "active") return;

    const landmarks = detectPose(camera, poseCanvas, performance.now());
    const result = repCounter.process(landmarks);

        // Check if a NEW rep was detected
    if (result.repDetected && result.reps > exerciseState.totalReps) {
        const formQuality = result.formIssue || "good";
        const stateResult = exerciseState.addRep(formQuality);
        updateSetDisplay();
        
        // HUD GAMIFICATION SCORING
        const baseScore = 5;
        let bonus = 0;
        if (result.isPerfect) {
            bonus = 5 + ((result.combo || 1) * 2);
            totalScore += baseScore + bonus;
            updateScoreDisplay(result.combo);
            
            if (result.combo % 3 === 0 && result.combo > 0) {
                 popFloatingReward(`Combo x${result.combo}! +${baseScore + bonus}`, true);
            } else {
                 popFloatingReward(`+${baseScore + bonus} Clean Rep`, true);
            }
        } else {
            totalScore += baseScore;
            updateScoreDisplay(result.combo);
            popFloatingReward(`+${baseScore}`, false);
        }

        // Record on backend
        if (window._workoutSessionId) {
            fetch("/session/rep", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: window._workoutSessionId, form_quality: formQuality }),
            }).catch(() => {});
        }

        // Set complete → start rest
        if (stateResult.setComplete && !stateResult.exerciseComplete) {
            addCoachMessage(`Set ${exerciseState.completedSets} done! Rest up.`);
            showFeedback("good_form");
            startRest();
        }

        // Exercise complete
        if (stateResult.exerciseComplete) {
            sessionPhase = "exerciseComplete";
            addCoachMessage(`${exerciseState.exercise} complete! Tap Next Exercise.`);
            showFeedback("good_form");
        }

        sendPoseEvent(result);
    } else if (!result.repDetected && exerciseState.repsInSet > 0) {
        repCountEl.textContent = exerciseState.repsInSet;
    }

    // Form feedback
    if (result.formIssue) {
        showFeedback(result.formIssue);
        lastFormIssue = result.formIssue;
        goodFormCounter = 0;
    } else if (lastFormIssue) {
        goodFormCounter++;
        if (goodFormCounter > 10) {
            showFeedback("good_form");
            lastFormIssue = null;
            goodFormCounter = 0;
        }
    }

    // Fatigue
    if (!fatigueWarned && repCounter.isFatigued()) {
        fatigueWarned = true;
        sendPoseEvent({ reps: result.reps, formIssue: "fatigue_detected", repDetected: false });
    }
}

function sendPoseEvent(result) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const now = Date.now();
    if (now - lastPoseEventTime < 4000) return;
    lastPoseEventTime = now;
    const ex = workoutPlan ? workoutPlan.exercises[currentExerciseIdx] : null;
    ws.send(JSON.stringify({
        type: "pose_event",
        data: {
            exercise: ex ? ex.exercise : "unknown",
            rep: exerciseState ? exerciseState.totalReps : result.reps,
            set: exerciseState ? exerciseState.currentSet : 1,
            form_issue: result.formIssue || null,
        },
    }));
}

// ============================================================
// Timer (shows exercise time, not total workout time)
// ============================================================
function updateTimer() {
    if (!exerciseStartTime) return;
    const elapsed = Math.floor((Date.now() - exerciseStartTime) / 1000);
    timerEl.textContent = `${Math.floor(elapsed / 60)}:${(elapsed % 60).toString().padStart(2, "0")}`;

    const speedEl = document.getElementById("speed-stat");
    if (speedEl && exerciseState && exerciseState.repsInSet > 0 && sessionPhase === "active" && !exerciseState.isTimed) {
        let speed = (elapsed / exerciseState.repsInSet).toFixed(1);
        speedEl.textContent = `${speed}s/rep`;
    } else if (speedEl) {
        speedEl.textContent = "--";
    }
}

// ============================================================
// Form Feedback
// ============================================================
function showFeedback(issue) {
    const messages = {
        leaning_forward:  { icon: "\u26A0\uFE0F", text: "Keep your chest up!",     good: false },
        not_deep_enough:  { icon: "\u2B07\uFE0F", text: "Go deeper!",               good: false },
        hips_sagging:     { icon: "\u26A0\uFE0F", text: "Keep hips level!",          good: false },
        hips_dropping:    { icon: "\u2B07\uFE0F", text: "Raise your hips!",          good: false },
        hips_too_high:    { icon: "\u2B06\uFE0F", text: "Lower your hips!",          good: false },
        fatigue_detected: { icon: "\u23F8\uFE0F", text: "Slowing down... rest?",    good: false },
        good_form:        { icon: "\u2705",        text: "Stable Form",               good: true  },
    };
    const msg = messages[issue] || { icon: "\u26A0\uFE0F", text: issue, good: false };
    feedbackIcon.textContent = msg.icon;
    feedbackText.textContent = msg.text;
    feedbackPill.classList.add("visible");
    feedbackPill.classList.toggle("good", msg.good);
    if (feedbackTimeout) clearTimeout(feedbackTimeout);
    feedbackTimeout = setTimeout(hideFeedback, 3000);

    // Voice cue for bad form only
    if (!msg.good) {
        speakFormFeedback(msg.text);
    }
}

function hideFeedback() {
    feedbackIcon.textContent = "\u2705";
    feedbackText.textContent = "Stable Form";
    feedbackPill.classList.add("visible");
    feedbackPill.classList.add("good");
    if (feedbackTimeout) { clearTimeout(feedbackTimeout); feedbackTimeout = null; }
}

// ============================================================
// Voice Feedback (Web Speech API)
// ============================================================
let lastSpokenIssue = null;
let lastSpeechTime = 0;
const SPEECH_COOLDOWN_MS = 4000;

function speakFormFeedback(text) {
    if (!window.speechSynthesis) return;
    const now = Date.now();
    if (text === lastSpokenIssue && now - lastSpeechTime < SPEECH_COOLDOWN_MS) return;
    lastSpokenIssue = text;
    lastSpeechTime = now;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-US';
    utterance.rate = 1.1;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    window.speechSynthesis.speak(utterance);
}

// ============================================================
// End Workout — Grounded in actual exerciseHistory
// ============================================================
async function endWorkout() {
    if (poseInterval) clearInterval(poseInterval);
    if (videoSendInterval) clearInterval(videoSendInterval);
    if (timerInterval) clearInterval(timerInterval);
    if (restInterval) clearInterval(restInterval);
    if (audioProcessor) { try { audioProcessor.disconnect(); } catch(e) {} }
    if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
    intentionalClose = true;
    if (ws) ws.close();

    // Save final exercise to history
    if (exerciseState) exerciseHistory.push(exerciseState.toSummary());

    const durationSec = Math.floor((Date.now() - workoutStartTime) / 1000);
    const mins = Math.floor(durationSec / 60);
    const secs = durationSec % 60;

    // Grounded totals from exerciseHistory
    const totalReps = exerciseHistory.reduce((sum, e) => sum + e.totalReps, 0);
    const totalSets = exerciseHistory.reduce((sum, e) => sum + e.setsCompleted, 0);
    const exerciseNames = exerciseHistory.map(e => e.exercise).join(", ");

    setState("complete");

    // Build exercise breakdown
    const breakdownHtml = exerciseHistory.map(e => {
        const rescued = e.rescued ? ' <span style="color:var(--accent);font-size:0.7rem;">RESCUED</span>' : '';
        return `<div style="font-size:0.85rem;color:var(--text-dim);padding:2px 0;">${e.exercise}: ${e.setsCompleted} sets, ${e.totalReps} reps${rescued}</div>`;
    }).join("");

    summaryStats.innerHTML = `
        <div class="summary-exercise">${exerciseNames || "Workout"}</div>
        <div class="summary-big-number">${totalScore}</div>
        <div class="summary-label">TOTAL SCORE \u00b7 ${totalSets} sets \u00b7 ${totalReps} reps</div>
        <div class="summary-duration">Duration: <span>${mins}m ${secs}s</span></div>
        <div style="margin:12px 0;border-top:1px solid var(--border);padding-top:12px;">
            ${breakdownHtml}
        </div>
        <div class="summary-form-score" id="form-score-line"><span class="loading"></span> Analyzing form...</div>
        <div class="summary-coaching" id="coaching-line"><span class="loading"></span> Coach is writing your debrief...</div>
    `;

    const badgesEl = document.getElementById("badges");
    const initialBadges = ["Mission Complete"];
    if (rescueCount > 0) initialBadges.push("Rescue Recovery");
    badgesEl.innerHTML = initialBadges.map(b => `<div class="badge">${b}</div>`).join("");

    // Fetch backend summary
    let formScore = "--";
    if (window._workoutSessionId) {
        try {
            const resp = await fetch("/session/end", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: window._workoutSessionId }),
            });
            const summary = await resp.json();
            if (summary.form_score !== undefined) formScore = summary.form_score.toFixed(1);

            const formScoreLine = document.getElementById("form-score-line");
            if (formScoreLine) {
                let issuesText = "";
                if (summary.form_issues && Object.keys(summary.form_issues).length > 0) {
                    issuesText = Object.entries(summary.form_issues)
                        .map(([k, v]) => `${formatFormIssueShort(k)} (${v}x)`)
                        .join(", ");
                }
                formScoreLine.innerHTML = `Form Score: <span>${formScore}</span>/10`;
                if (issuesText) {
                    formScoreLine.insertAdjacentHTML("afterend", `<div class="summary-issues">${issuesText}</div>`);
                }
            }

            const coachingLine = document.getElementById("coaching-line");
            if (coachingLine) {
                coachingLine.textContent = summary.coaching_summary || "Great session! Keep it up.";
            }

            const badges = ["Mission Complete"];
            const numFormScore = parseFloat(formScore);
            if (!isNaN(numFormScore) && numFormScore >= 8) badges.push("Clean Form");
            if (rescueCount > 0) badges.push("Rescue Recovery");
            if (mins >= 20) badges.push("Endurance");
            if (totalReps >= 50) badges.push("Rep Machine");
            badgesEl.innerHTML = badges.map(b => `<div class="badge">${b}</div>`).join("");
        } catch (err) {
            const formScoreLine = document.getElementById("form-score-line");
            if (formScoreLine) formScoreLine.textContent = "Form Score: --/10";
            const coachingLine = document.getElementById("coaching-line");
            if (coachingLine) coachingLine.textContent = "Great workout! Session saved.";
        }
    }

    audioProcessor = null;
}

// ============================================================
// Helpers
// ============================================================
function addCoachMessage(text) {
    const div = document.createElement("div");
    div.className = "coach-msg";
    div.textContent = text;
    messagesList.appendChild(div);
    messagesList.scrollTop = messagesList.scrollHeight;
    while (messagesList.children.length > 20) messagesList.removeChild(messagesList.firstChild);
}

function formatFormIssueShort(issue) {
    const map = {
        leaning_forward: "Chest up", not_deep_enough: "Go deeper",
        hips_sagging: "Hips level", hips_dropping: "Raise hips",
        hips_too_high: "Lower hips", fatigue_detected: "Fatigue",
    };
    return map[issue] || issue;
}

function b64UrlSafeToStandard(b64) {
    let s = b64.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    return s;
}

function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
}

function base64ToArrayBuffer(base64) {
    const std = b64UrlSafeToStandard(base64);
    const binary = atob(std);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
}
