@echo off
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Starting FastAPI backend on port 8000...
start "D365 Backend" cmd /k "uvicorn backend.main:app --reload --port 8000 --host 0.0.0.0"

echo Waiting for backend to start...
timeout /t 3 /nobreak >nul

echo Starting Streamlit frontend on port 8501...
start "D365 Frontend" cmd /k "streamlit run frontend/app.py --server.port 8501"

echo.
echo ========================================================
echo  D365 Project Lifecycle Integration Agent
echo ========================================================
echo  Frontend  : http://localhost:8501
echo  API Docs  : http://localhost:8000/docs
echo ========================================================
