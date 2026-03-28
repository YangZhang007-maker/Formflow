/**
 * Pose detection + rep counting using MediaPipe Tasks Vision.
 * Runs entirely in the browser.
 */

import { PoseLandmarker, FilesetResolver, DrawingUtils } from
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18";

let poseLandmarker = null;
let drawingUtils = null;

export async function initPose(canvasElement) {
    const vision = await FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm"
    );

    poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
        baseOptions: {
            modelAssetPath: "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
            delegate: "GPU",
        },
        runningMode: "VIDEO",
        numPoses: 1,
    });

    const ctx = canvasElement.getContext("2d");
    drawingUtils = new DrawingUtils(ctx);

    return poseLandmarker;
}

/**
 * Process a video frame and return landmarks + drawn skeleton.
 */
export function detectPose(videoElement, canvasElement, timestamp) {
    if (!poseLandmarker) return null;

    const results = poseLandmarker.detectForVideo(videoElement, timestamp);

    // Draw skeleton
    const ctx = canvasElement.getContext("2d");
    ctx.clearRect(0, 0, canvasElement.width, canvasElement.height);

    if (results.landmarks && results.landmarks.length > 0) {
        for (const landmarks of results.landmarks) {
            drawingUtils.drawLandmarks(landmarks, {
                radius: 3,
                color: "#4ade80",
                lineWidth: 1,
            });
            drawingUtils.drawConnectors(landmarks, PoseLandmarker.POSE_CONNECTIONS, {
                color: "#4ade8066",
                lineWidth: 2,
            });
        }
        return results.landmarks[0];
    }
    return null;
}

/**
 * Calculate angle between three landmarks (in degrees).
 */
export function getAngle(a, b, c) {
    const radians = Math.atan2(c.y - b.y, c.x - b.x) - Math.atan2(a.y - b.y, a.x - b.x);
    let angle = Math.abs(radians * (180 / Math.PI));
    if (angle > 180) angle = 360 - angle;
    return angle;
}

/**
 * Get landmark visibility (0-1). MediaPipe landmarks have a visibility field.
 */
function lm_visibility(landmark) {
    return landmark.visibility !== undefined ? landmark.visibility : 1;
}

// MediaPipe Pose landmark indices
export const LANDMARKS = {
    LEFT_SHOULDER: 11,
    RIGHT_SHOULDER: 12,
    LEFT_ELBOW: 13,
    RIGHT_ELBOW: 14,
    LEFT_WRIST: 15,
    RIGHT_WRIST: 16,
    LEFT_HIP: 23,
    RIGHT_HIP: 24,
    LEFT_KNEE: 25,
    RIGHT_KNEE: 26,
    LEFT_ANKLE: 27,
    RIGHT_ANKLE: 28,
};

/**
 * Rep counter state machine.
 */
export class RepCounter {
    constructor(exercise) {
        this.exercise = exercise;
        this.reps = 0;
        this.state = "idle"; // idle → up → down → up (idle = waiting for stable starting position)
        this.formIssues = [];
        this.currentRepIssues = []; // Form issues in current active rep cycle
        this.comboCount = 0;
        this.lastRepTime = Date.now();
        this.stableFrames = 0; // Count frames in starting position before counting
        this.STABLE_THRESHOLD = 8; // Need ~0.8s of stable starting pose (reduced for responsiveness)
    }

    /**
     * Process landmarks and return { reps, formIssue, repDetected }.
     */
    process(landmarks) {
        if (!landmarks) return { reps: this.reps, formIssue: null, repDetected: false, isPerfect: false, combo: this.comboCount };

        const L = LANDMARKS;

        // Check landmark visibility — need at least one side visible
        const leftVis = Math.min(
            lm_visibility(landmarks[L.LEFT_HIP]),
            lm_visibility(landmarks[L.LEFT_KNEE]),
            lm_visibility(landmarks[L.LEFT_ANKLE])
        );
        const rightVis = Math.min(
            lm_visibility(landmarks[L.RIGHT_HIP]),
            lm_visibility(landmarks[L.RIGHT_KNEE]),
            lm_visibility(landmarks[L.RIGHT_ANKLE])
        );
        if (leftVis < 0.3 && rightVis < 0.3) {
            return { reps: this.reps, formIssue: null, repDetected: false, isPerfect: false, combo: this.comboCount };
        }

        if (this.exercise === "squat") {
            return this._processSquat(landmarks, L);
        } else if (this.exercise === "pushup") {
            return this._processPushup(landmarks, L);
        } else if (this.exercise === "plank") {
            return this._processPlank(landmarks, L);
        }

        return { reps: this.reps, formIssue: null, repDetected: false, isPerfect: false, combo: this.comboCount };
    }

    // Use the more visible side for angle calculations
    _bestSide(lm, L) {
        const leftVis = lm_visibility(lm[L.LEFT_HIP]) + lm_visibility(lm[L.LEFT_KNEE]);
        const rightVis = lm_visibility(lm[L.RIGHT_HIP]) + lm_visibility(lm[L.RIGHT_KNEE]);
        return rightVis > leftVis ? "right" : "left";
    }

    _processSquat(lm, L) {
        const side = this._bestSide(lm, L);
        const hip = side === "right" ? L.RIGHT_HIP : L.LEFT_HIP;
        const knee = side === "right" ? L.RIGHT_KNEE : L.LEFT_KNEE;
        const ankle = side === "right" ? L.RIGHT_ANKLE : L.LEFT_ANKLE;
        const shoulder = side === "right" ? L.RIGHT_SHOULDER : L.LEFT_SHOULDER;

        const kneeAngle = getAngle(lm[hip], lm[knee], lm[ankle]);
        const hipAngle = getAngle(lm[shoulder], lm[hip], lm[knee]);

        let formIssue = null;
        let repDetected = false;
        let isPerfect = false;

        // Wait for stable standing position before counting
        if (this.state === "idle") {
            if (kneeAngle > 155) {
                this.stableFrames++;
                if (this.stableFrames >= this.STABLE_THRESHOLD) {
                    this.state = "up";
                }
            } else {
                this.stableFrames = 0;
            }
            return { reps: this.reps, formIssue: null, repDetected: false, isPerfect: false, combo: this.comboCount };
        }

        // Form checks (only when actively exercising)
        if (hipAngle < 70) {
            formIssue = "leaning_forward";
            this.currentRepIssues.push(formIssue);
        }

        // Rep counting: down when knee angle < 100, up when > 155
        if (kneeAngle < 100 && this.state === "up") {
            this.state = "down";
            if (kneeAngle > 80) {
                formIssue = formIssue || "not_deep_enough";
                this.currentRepIssues.push("not_deep_enough");
            }
        } else if (kneeAngle > 155 && this.state === "down") {
            this.state = "up";
            this.reps++;
            repDetected = true;
            this.lastRepTime = Date.now();
            
            isPerfect = this.currentRepIssues.length === 0;
            if (isPerfect) this.comboCount++;
            else this.comboCount = 0;
            this.currentRepIssues = []; // reset
        }

        return { reps: this.reps, formIssue, repDetected, isPerfect, combo: this.comboCount };
    }

    _processPushup(lm, L) {
        const side = this._bestSide(lm, L);
        const shoulder = side === "right" ? L.RIGHT_SHOULDER : L.LEFT_SHOULDER;
        const elbow = side === "right" ? L.RIGHT_ELBOW : L.LEFT_ELBOW;
        const wrist = side === "right" ? L.RIGHT_WRIST : L.LEFT_WRIST;
        const hip = side === "right" ? L.RIGHT_HIP : L.LEFT_HIP;
        const ankle = side === "right" ? L.RIGHT_ANKLE : L.LEFT_ANKLE;

        const elbowAngle = getAngle(lm[shoulder], lm[elbow], lm[wrist]);
        const bodyAngle = getAngle(lm[shoulder], lm[hip], lm[ankle]);

        let formIssue = null;
        let repDetected = false;
        let isPerfect = false;

        // Wait for stable plank/up position
        if (this.state === "idle") {
            if (elbowAngle > 155) {
                this.stableFrames++;
                if (this.stableFrames >= this.STABLE_THRESHOLD) {
                    this.state = "up";
                }
            } else {
                this.stableFrames = 0;
            }
            return { reps: this.reps, formIssue: null, repDetected: false, isPerfect: false, combo: this.comboCount };
        }

        // Form: body should be straight
        if (bodyAngle < 150) {
            formIssue = "hips_sagging";
            this.currentRepIssues.push(formIssue);
        }

        // Rep counting: down when elbow < 90, up when > 155
        if (elbowAngle < 90 && this.state === "up") {
            this.state = "down";
        } else if (elbowAngle > 155 && this.state === "down") {
            this.state = "up";
            this.reps++;
            repDetected = true;
            this.lastRepTime = Date.now();
            
            isPerfect = this.currentRepIssues.length === 0;
            if (isPerfect) this.comboCount++;
            else this.comboCount = 0;
            this.currentRepIssues = []; // reset
        }

        return { reps: this.reps, formIssue, repDetected, isPerfect, combo: this.comboCount };
    }

    _processPlank(lm, L) {
        const side = this._bestSide(lm, L);
        const shoulder = side === "right" ? L.RIGHT_SHOULDER : L.LEFT_SHOULDER;
        const hip = side === "right" ? L.RIGHT_HIP : L.LEFT_HIP;
        const ankle = side === "right" ? L.RIGHT_ANKLE : L.LEFT_ANKLE;

        const bodyAngle = getAngle(lm[shoulder], lm[hip], lm[ankle]);

        let formIssue = null;

        if (bodyAngle < 150) {
            formIssue = "hips_dropping";
        } else if (bodyAngle > 190) {
            formIssue = "hips_too_high";
        }

        // Planks count time, not reps — reps stays 0, we track elapsed time externally
        return { reps: this.reps, formIssue, repDetected: false, isPerfect: false, combo: 0 };
    }

    /**
     * Check if user is fatiguing (reps slowing down).
     */
    isFatigued() {
        return (Date.now() - this.lastRepTime) > 8000 && this.reps > 3;
    }
}
