#!/bin/bash
# RepWise — Automated Cloud Run Deployment
# Usage: ./deploy.sh [PROJECT_ID] [API_KEY]
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Billing enabled on the GCP project
#
# This script:
#   1. Sets the GCP project
#   2. Enables required APIs (Cloud Run, Firestore, Cloud Build, Artifact Registry)
#   3. Creates Firestore database if not exists
#   4. Builds and deploys the container to Cloud Run
#   5. Outputs the live URL

set -euo pipefail

# --- Configuration ---
PROJECT_ID="${1:-repwise-490117}"
API_KEY="${2:-}"
REGION="us-central1"
SERVICE_NAME="repwise"
MEMORY="512Mi"
TIMEOUT="3600"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- Validate ---
command -v gcloud >/dev/null 2>&1 || err "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"

if [ -z "$API_KEY" ]; then
    if [ -f .env ]; then
        API_KEY=$(grep GOOGLE_API_KEY .env | cut -d= -f2)
    fi
    if [ -z "$API_KEY" ]; then
        err "API key required. Usage: ./deploy.sh PROJECT_ID API_KEY"
    fi
fi

log "Deploying RepWise to project: $PROJECT_ID (region: $REGION)"

# --- Step 1: Set project ---
log "Setting GCP project..."
gcloud config set project "$PROJECT_ID" --quiet

# --- Step 2: Enable APIs ---
log "Enabling required APIs..."
gcloud services enable \
    run.googleapis.com \
    firestore.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    --quiet

# --- Step 3: Create Firestore (if not exists) ---
log "Checking Firestore database..."
if ! gcloud firestore databases describe --quiet 2>/dev/null; then
    log "Creating Firestore database..."
    gcloud firestore databases create --location="$REGION" --quiet
else
    log "Firestore database already exists."
fi

# --- Step 4: Run tests ---
log "Running tests..."
if [ -d ".venv" ]; then
    .venv/bin/python -m pytest tests/ -q --tb=short || err "Tests failed. Fix before deploying."
    log "All tests passed."
else
    warn "No .venv found — skipping tests. Run 'pytest tests/' manually."
fi

# --- Step 5: Deploy to Cloud Run ---
log "Building and deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --region "$REGION" \
    --set-env-vars "GOOGLE_API_KEY=$API_KEY,GOOGLE_GENAI_USE_VERTEXAI=FALSE" \
    --allow-unauthenticated \
    --memory "$MEMORY" \
    --timeout "$TIMEOUT" \
    --session-affinity \
    --quiet

# --- Step 6: Get URL ---
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region "$REGION" \
    --format="value(status.url)")

echo ""
log "========================================="
log "  RepWise deployed successfully!"
log "  URL: $SERVICE_URL"
log "========================================="
echo ""
