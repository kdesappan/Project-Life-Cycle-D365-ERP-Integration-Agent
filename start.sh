#!/usr/bin/env bash
set -e

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Starting FastAPI backend (port 8000)..."
uvicorn backend.main:app --reload --port 8000 --host 0.0.0.0 &
BACKEND_PID=$!

sleep 2

echo "Starting Streamlit frontend (port 8501)..."
streamlit run frontend/app.py --server.port 8501 &
FRONTEND_PID=$!

echo ""
echo "=================================================="
echo " D365 Project Lifecycle Integration Agent"
echo "=================================================="
echo " Frontend : http://localhost:8501"
echo " API Docs : http://localhost:8000/docs"
echo "=================================================="

wait $BACKEND_PID $FRONTEND_PID
