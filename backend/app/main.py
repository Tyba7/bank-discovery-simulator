"""HTTP API for the simulator. Run: uv run uvicorn app.main:app --reload

The browser only ever sees public client facts, the catalogue and the conversation. Hidden needs, unlock
state and rule details are returned only in the feedback, after the student submits (NFR-08, BR-16).
Handlers are plain `def`: model calls block, so FastAPI runs them in its thread pool.
"""

import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from app.checks import MAX_MESSAGE_CHARS
from app.coach import MAX_SUMMARY_CHARS, Recommendation, Submission, coach
from app.config import ROLES, load_role_settings
from app.content import Content, load_content
from app.interview import build_interview_graph
from app.llm import LLM, MODEL_ERRORS, build_llms
from app.sessions import Session, SessionStore

log = logging.getLogger(__name__)

MAX_TURNS = 40
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"  # built by `npm run build`
# Same-origin only. The API docs (/docs) load their own scripts from a CDN, so they are left out.
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
MODEL_DOWN = "The AI service is not responding right now. Please wait a moment and try again."


# --- what the browser may see ---


class ClientCard(BaseModel):
    id: str
    name: str
    age: int
    occupation: str
    background: str
    stated_goal: str


class ProductCard(BaseModel):
    id: str
    name: str
    category: str
    features: list[str]
    limitations: list[str]


class Message(BaseModel):
    role: Literal["student", "client"]
    content: str


class StartSession(BaseModel):
    client_id: str = Field(max_length=100)


class StudentMessage(BaseModel):
    # The input check answers anything over MAX_MESSAGE_CHARS in character; this only refuses absurd bodies.
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS * 4)


class SubmissionIn(BaseModel):
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    recommendations: list[Recommendation] = Field(default=[], max_length=6)


class SessionOut(BaseModel):
    session_id: str
    client: ClientCard
    messages: list[Message]
    turns_left: int
    finished: bool
    feedback: dict | None = None


class Reply(BaseModel):
    reply: str
    turns_left: int


def client_card(content: Content, client_id: str) -> ClientCard:
    c = content.clients[client_id]
    return ClientCard(
        id=c.id, name=c.name, age=c.age, occupation=c.occupation, background=c.background, stated_goal=c.stated_goal
    )


def student_feedback(feedback) -> dict:
    out = asdict(feedback)
    out.pop("checks"), out.pop("events")  # internal; they go to the logs, not to the student
    return out


# --- app ---


def create_app(llm: LLM | None = None, content: Content | None = None) -> FastAPI:
    """llm and content can be injected (tests: one model for every role); otherwise they come from .env (one client
    per role, see config.load_role_settings) and content/ at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        for noisy in ("LiteLLM", "httpx"):  # one line per HTTP call; app.telemetry already records every model call
            logging.getLogger(noisy).setLevel(logging.WARNING)
        llms = dict.fromkeys(ROLES, llm) if llm else build_llms(load_role_settings())
        app.state.content = content or load_content()
        app.state.llms = llms
        checkpointer = InMemorySaver()
        app.state.graph = build_interview_graph(app.state.content, llms, checkpointer)
        app.state.sessions = SessionStore(checkpointer)
        log.info("ready: models %s, %d clients", models(app), len(app.state.content.clients))
        yield

    app = FastAPI(title="Bank Client Discovery Simulator", lifespan=lifespan)

    def models(app: FastAPI) -> dict[str, str]:
        return {role: llm.s.llm_model for role, llm in app.state.llms.items()}

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
            response.headers["Content-Security-Policy"] = CSP
        return response

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):  # never a stack trace or an error page in the browser
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})

    def session_or_404(request: Request, session_id: str) -> Session:
        session = request.app.state.sessions.get(session_id)
        if not session:
            raise HTTPException(404, "This session does not exist or has expired. Please start a new interview.")
        return session

    def messages(request: Request, session: Session) -> list[Message]:
        values = request.app.state.graph.get_state(session.config()).values
        return [Message(**t) for t in values.get("transcript", [])]

    def turns_used(msgs: list[Message]) -> int:
        return sum(m.role == "student" for m in msgs)

    def session_out(request: Request, session: Session) -> SessionOut:
        msgs = messages(request, session)
        return SessionOut(
            session_id=session.id,
            client=client_card(request.app.state.content, session.client_id),
            messages=msgs,
            turns_left=MAX_TURNS - turns_used(msgs),
            finished=session.feedback is not None,
            feedback=student_feedback(session.feedback) if session.feedback else None,
        )

    @app.get("/api/health")
    def health(request: Request) -> dict:
        return {"status": "ok", "models": models(request.app)}

    @app.get("/api/clients")
    def clients(request: Request) -> list[ClientCard]:
        return [client_card(request.app.state.content, cid) for cid in request.app.state.content.clients]

    @app.get("/api/products")
    def products(request: Request) -> list[ProductCard]:
        content = request.app.state.content
        return [
            ProductCard(
                id=p.id,
                name=p.name,
                category=content.taxonomy.product_categories[p.category],
                features=p.features,
                limitations=p.limitations,
            )
            for p in content.products.values()
        ]

    @app.post("/api/sessions", status_code=201)
    def start(request: Request, body: StartSession) -> SessionOut:
        if body.client_id not in request.app.state.content.clients:
            raise HTTPException(404, f"Unknown client '{body.client_id}'.")
        session = request.app.state.sessions.create(body.client_id)
        try:
            with session.lock:
                request.app.state.graph.invoke({"client_id": body.client_id}, session.config())
        except MODEL_ERRORS:
            log.exception("opening failed")
            request.app.state.sessions.drop(session.id)
            raise HTTPException(503, MODEL_DOWN) from None
        return session_out(request, session)

    @app.get("/api/sessions/{session_id}")
    def get_session(request: Request, session_id: str) -> SessionOut:
        return session_out(request, session_or_404(request, session_id))

    @app.post("/api/sessions/{session_id}/messages")
    def send(request: Request, session_id: str, body: StudentMessage) -> Reply:
        session = session_or_404(request, session_id)
        graph = request.app.state.graph
        if not session.lock.acquire(blocking=False):
            raise HTTPException(409, "The client is still answering your last message.")
        try:
            if session.feedback is not None:
                raise HTTPException(409, "This interview has ended. Start a new one to practise again.")
            if turns_used(messages(request, session)) >= MAX_TURNS:
                raise HTTPException(409, "This interview has reached its limit. Please submit your summary.")
            before = graph.get_state(session.config()).config["configurable"]["checkpoint_id"]
            try:
                state = graph.invoke({"student_message": body.message}, session.config())
            except MODEL_ERRORS:
                # A failed turn must leave no trace (no half-applied unlocks): continue from the checkpoint before it.
                log.exception("turn failed in session %s", session.id)
                session.head = before
                raise HTTPException(503, MODEL_DOWN) from None
            session.head = None
            msgs = [Message(**t) for t in state["transcript"]]
            return Reply(reply=msgs[-1].content, turns_left=MAX_TURNS - turns_used(msgs))
        finally:
            session.lock.release()

    @app.post("/api/sessions/{session_id}/feedback")
    def feedback(request: Request, session_id: str, body: SubmissionIn) -> dict:
        session = session_or_404(request, session_id)
        content = request.app.state.content
        unknown = sorted({r.product_id for r in body.recommendations} - content.products.keys())
        if unknown:
            raise HTTPException(422, f"Unknown product id: {', '.join(unknown)}")
        if not session.lock.acquire(blocking=False):
            raise HTTPException(409, "Please wait for the client's last answer.")
        try:
            if session.feedback is not None:
                return student_feedback(session.feedback)  # submitting twice returns the same feedback
            state = request.app.state.graph.get_state(session.config()).values
            submission = Submission(summary=body.summary, recommendations=body.recommendations)
            llms = request.app.state.llms
            # Suggested questions are checked by the classifier the student actually faces, not the coach's model.
            result = coach(content, llms["coach"], state, submission, checker=llms["classifier"])
            for e in result.events:
                log.info("coach event %s in session %s: %s", e["code"], session.id, e["detail"])
            session.submission, session.feedback = submission, result
            return student_feedback(result)
        finally:
            session.lock.release()

    @app.get("/api/sessions/{session_id}/export")
    def export(request: Request, session_id: str) -> JSONResponse:
        session = session_or_404(request, session_id)
        out = session_out(request, session)
        body = {
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "models": models(request.app),
            "client": out.client.model_dump(),
            "conversation": [m.model_dump() for m in out.messages],
            "submission": session.submission.model_dump() if session.submission else None,
            "feedback": out.feedback,
        }
        filename = f"interview-{session.client_id}-{session.id[:8]}.json"
        return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    if FRONTEND.is_dir():  # one process serves the API and the built web UI; mounted last so /api wins
        app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
    return app


app = create_app()
