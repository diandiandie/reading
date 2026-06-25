"""启动入口：python run.py 或 uvicorn run:app --host 0.0.0.0 --port 8000"""

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("run:app", host="0.0.0.0", port=8000, reload=True)
