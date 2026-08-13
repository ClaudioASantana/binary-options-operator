#!/bin/bash

# Navigate to script directory
cd "$(dirname "$0")"

# Colors for log output
COLOR_BLUE="\033[1;34m"
COLOR_GREEN="\033[1;32m"
COLOR_RED="\033[1;31m"
COLOR_RESET="\033[0m"

log_info() {
  echo -e "${COLOR_BLUE}[INFO] $(date '+%Y-%m-%d %H:%M:%S')${COLOR_RESET} $1"
}

log_success() {
  echo -e "${COLOR_GREEN}[SUCCESS] $(date '+%Y-%m-%d %H:%M:%S')${COLOR_RESET} $1"
}

log_error() {
  echo -e "${COLOR_RED}[ERROR] $(date '+%Y-%m-%d %H:%M:%S')${COLOR_RESET} $1"
}

# Processes PIDs
BACKEND_PID=""
FRONTEND_PID=""

# Cleanup function to kill background processes on exit
cleanup() {
  echo ""
  log_info "Shutting down development servers..."
  
  if [ -n "$BACKEND_PID" ]; then
    log_info "Stopping Backend (PID $BACKEND_PID)..."
    kill -TERM "$BACKEND_PID" 2>/dev/null
    wait "$BACKEND_PID" 2>/dev/null
  fi
  
  if [ -n "$FRONTEND_PID" ]; then
    log_info "Stopping Frontend (PID $FRONTEND_PID)..."
    kill -TERM "$FRONTEND_PID" 2>/dev/null
    wait "$FRONTEND_PID" 2>/dev/null
  fi
  
  log_success "All development servers stopped. Goodbye!"
  exit 0
}

# Trap signals for cleanup
trap cleanup SIGINT SIGTERM EXIT

# 1. Verify Backend Virtual Environment
if [ ! -d "backend/venv" ]; then
  log_error "Backend virtual environment 'backend/venv' not found."
  log_info "Please setup the virtual environment and install requirements first:"
  log_info "  python3 -m venv backend/venv"
  log_info "  source backend/venv/bin/activate && pip install -r backend/requirements.txt"
  exit 1
fi

# 2. Verify Frontend Dependencies
if [ ! -d "frontend/node_modules" ]; then
  log_info "Frontend 'node_modules' not found. Installing dependencies..."
  (cd frontend && npm install)
  if [ $? -ne 0 ]; then
    log_error "Failed to install frontend dependencies."
    exit 1
  fi
  log_success "Frontend dependencies installed successfully."
fi

# 3. Start Backend
log_info "Starting Backend (FastAPI) on port 8020..."
cd backend
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload &
BACKEND_PID=$!
cd ..

# Wait a moment for backend to initialize
sleep 2

# 4. Start Frontend
log_info "Starting Frontend (Next.js) on port 3020..."
cd frontend
npm run dev -- -H 0.0.0.0 -p 3020 &
FRONTEND_PID=$!
cd ..

log_success "Development servers started!"
log_info "- Frontend: http://localhost:3020"
log_info "- Backend API: http://localhost:8020"
log_info "Press Ctrl+C to stop both servers."

# Keep script running and wait for background processes
wait
