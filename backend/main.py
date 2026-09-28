"""
CrowdSense Backend Main Entry Wrapper Module.
Re-exports the primary FastAPI application from dashboard.py for backward compatibility.
"""

from dashboard import app, engine

if __name__ == "__main__":
    import uvicorn
    from core.config import HOST, PORT
    uvicorn.run(app, host=HOST, port=PORT)
