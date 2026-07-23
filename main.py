"""
MindCheck — a wellness check-in AI chat assistant.

FastAPI backend that:
  - Serves the static frontend (single-container deploy)
  - Exposes POST /api/chat which streams a response from an LLM (SSE)
  - Keeps the API key server-side only (never sent to the client)
  - Runs a lightweight keyword safety check before calling the LLM

This is a course/portfolio project, NOT a clinical tool. It is not a
substitute for professional mental health care.
"""

import json
import os
from pathlib import Path
from typing import List, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel, Field

load_dotenv()

API_KEY = os.getenv("GROQ_API_KEY")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

if not API_KEY:
    # Fail loudly at startup rather than silently 500-ing on first request.
    raise RuntimeError(
        "GROQ_API_KEY is not set. Add it to your .env file (local) "
        "or as an environment variable in your AWS App Runner service."
    )

client = Groq(api_key=API_KEY)

app = FastAPI(title="MindCheck API")

SYSTEM_PROMPT = """You are MindCheck, a warm, supportive wellness check-in companion.

Your role:
- Listen actively and reflect back what the person shares.
- Ask gentle, open-ended follow-up questions about mood, sleep, stress, and daily habits.
- Offer general, well-established wellness practices (breathing exercises, journaling
  prompts, grounding techniques, sleep hygiene, gentle movement) when relevant.
- Encourage the person to connect with a licensed therapist, counselor, or doctor for
  anything beyond general wellness support.

Strict boundaries:
- You are NOT a therapist and do not provide therapy, diagnosis, or medical advice.
- Never diagnose or label what the person might have (no naming conditions).
- Never provide instructions related to self-harm, suicide methods, or dosages of any
  substance, under any framing.
- If the person expresses thoughts of suicide, self-harm, or being in crisis, respond
  with warmth, take it seriously, and encourage them to reach out to a crisis line or
  emergency services immediately. Do not try to talk them out of it alone.
- Keep responses conversational and concise (a few sentences), not clinical essays.
"""

CRISIS_KEYWORDS = [
    "kill myself", "suicide", "end my life", "want to die", "self harm",
    "self-harm", "hurt myself", "no reason to live", "better off dead",
]

CRISIS_NOTICE = (
    "I'm really glad you told me. What you're feeling matters, and you don't have "
    "to go through it alone. If you're in immediate danger, please contact your "
    "local emergency number now. You can also reach the 988 Suicide & Crisis "
    "Lifeline (call or text 988 in the US) or the Crisis Text Line (text HOME to "
    "741741) any time, day or night. Would you like to tell me a bit more about "
    "how you're doing right now?"
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


def contains_crisis_language(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in CRISIS_KEYWORDS)


def sse_event(data: str) -> str:
    """Format a chunk as a Server-Sent Events data frame."""
    return f"data: {json.dumps({'delta': data})}\n\n"


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    last_user_msg = req.messages[-1].content

    def stream():
        # Safety net: short-circuit with crisis resources instead of relying
        # solely on the model's judgment for high-risk language.
        if contains_crisis_language(last_user_msg):
            yield sse_event(CRISIS_NOTICE)
            yield "data: [DONE]\n\n"
            return

        # Groq uses "user" / "assistant" roles (no "model", no inline "system" turn).
        groq_messages = [
            {
                "role": "assistant" if m.role == "assistant" else "user",
                "content": m.content
            }
            for m in req.messages
        ]

        try:
            stream_resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                *groq_messages,
            ],
            stream=True,
            temperature=0.7,
            max_tokens=500,
            )

            for chunk in stream_resp:
                delta = chunk.choices[0].delta.content
                if delta :
                    yield sse_event(delta)
        except Exception as exc:  # surface a readable error to the client
            yield sse_event(f"\n\n[Error contacting the AI service: {exc}]")
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve the static frontend last so it doesn't shadow the /api routes.
FRONTEND_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")