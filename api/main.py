from fastapi import FastAPI
from pydantic import BaseModel
import requests

app = FastAPI()

class ChatRequest(BaseModel):
    message: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat")
def chat(req: ChatRequest):

    response = requests.post(
        "http://127.0.0.1:11434/api/generate",
        json={
            "model": "qwen2.5-coder:7b-instruct-q4_K_M",
            "prompt": req.message,
            "stream": False
        },
        timeout=120
    )

    data = response.json()

    return {
        "response": data["response"]
    }