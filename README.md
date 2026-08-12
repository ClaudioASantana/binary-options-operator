# Binary Options Operator

This system includes a FastAPI backend (to operate volatility bots on the Deriv platform) and a Next.js frontend to monitor and configure the bots.

## Local Development (Dev Mode)

To start both the frontend and backend servers concurrently with hot-reload enabled, run the following command from the root of the project:

```bash
./start-dev.sh
```

This script will:
1. Verify that your backend Python virtual environment (`backend/venv`) is available.
2. Check if frontend dependencies are installed (`frontend/node_modules`) and run `npm install` if they are missing.
3. Launch the FastAPI server on [http://localhost:8000](http://localhost:8000) with hot-reload enabled.
4. Launch the Next.js frontend on [http://localhost:3000](http://localhost:3000).
5. Cleanly shut down both processes when you press `Ctrl+C`.

### Prerequisites

Ensure you have created the backend virtual environment and installed its dependencies:
```bash
python3 -m venv backend/venv
source backend/venv/bin/activate
pip install -r backend/requirements.txt
```
