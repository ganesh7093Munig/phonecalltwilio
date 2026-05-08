"""
=============================================================================
AI Communication Platform - Twilio Phone Call & SMS Backend
=============================================================================
A FastAPI backend that lets you trigger phone calls and SMS messages to
registered users via simple natural-language commands (e.g. "Call Alice").

Architecture (all in one file):
  - Models      : Pydantic schemas for User, Log, and request payloads
  - Database    : Lightweight JSON file-based persistence (no SQL needed)
  - TwilioService: Wrapper around the Twilio REST client for calls & SMS
  - Orchestrator : Parses natural-language commands and dispatches actions
  - API Routes  : FastAPI endpoints exposed under /api
  - App entry   : FastAPI app creation, CORS, router registration, uvicorn

Environment variables required (put in a .env file):
  TWILIO_ACCOUNT_SID   - Your Twilio account SID
  TWILIO_AUTH_TOKEN    - Your Twilio auth token
  TWILIO_PHONE_NUMBER  - Your Twilio "from" phone number (E.164 format)
  PORT                 - (optional) HTTP port, default 8000
  HOST                 - (optional) bind host, default 0.0.0.0

Run:
  pip install fastapi uvicorn twilio python-dotenv pydantic
  python phonecall_twilio_app.py
=============================================================================
"""

# ---------------------------------------------------------------------------
# Standard library & third-party imports
# ---------------------------------------------------------------------------
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from twilio.rest import Client

# Load .env file values into os.environ before anything else
load_dotenv()


# =============================================================================
# SECTION 1 – PYDANTIC MODELS
# These define the shape of data flowing through the API and stored on disk.
# =============================================================================

class User(BaseModel):
    """A registered contact that can receive calls or SMS messages."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str          # Human-readable name used in commands ("Call Alice")
    phone_number: str      # E.164 format, e.g. "+14155552671"


class UserCreate(BaseModel):
    """Payload for POST /api/users – only username + phone are required."""
    username: str
    phone_number: str


class UserUpdate(BaseModel):
    """Payload for PUT /api/users/{id} – all fields optional (partial update)."""
    username: Optional[str] = None
    phone_number: Optional[str] = None


class CommunicationLog(BaseModel):
    """A record of every call or SMS attempted by the platform."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    recipient_name: str    # Username of the target user
    recipient_phone: str   # Phone number called/texted
    action: str            # "call" or "sms"
    message: str           # The text spoken or sent
    status: str            # "success" or "failed"
    sid: Optional[str] = None  # Twilio message/call SID for tracking


class CommandRequest(BaseModel):
    """Payload for POST /api/process-command – the natural-language instruction."""
    command: str           # e.g. "Call Alice and tell her dinner is ready"


# =============================================================================
# SECTION 2 – JSON FILE DATABASE
# Stores Users and Logs as plain JSON files in a /data directory.
# Simple and portable – no database server required.
# =============================================================================

# Resolve paths relative to this script's location so the app can be run
# from any working directory.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(_BASE_DIR, "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LOGS_FILE  = os.path.join(DATA_DIR, "logs.json")


def _ensure_data_files() -> None:
    """Create the data directory and empty JSON files if they don't exist yet."""
    os.makedirs(DATA_DIR, exist_ok=True)
    for path in (USERS_FILE, LOGS_FILE):
        if not os.path.exists(path):
            with open(path, "w") as f:
                json.dump([], f)


def get_users() -> List[User]:
    """Read all users from disk and return them as a list of User objects."""
    _ensure_data_files()
    with open(USERS_FILE, "r") as f:
        return [User(**u) for u in json.load(f)]


def save_users(users: List[User]) -> None:
    """Persist the full list of User objects to disk (overwrites the file)."""
    _ensure_data_files()
    with open(USERS_FILE, "w") as f:
        json.dump([u.model_dump() for u in users], f, indent=4)


def get_user_by_name(username: str) -> Optional[User]:
    """Case-insensitive lookup; returns None if the username is not registered."""
    for user in get_users():
        if user.username.lower() == username.lower():
            return user
    return None


def add_log(log: CommunicationLog) -> None:
    """Append a single CommunicationLog entry to the logs file."""
    _ensure_data_files()
    with open(LOGS_FILE, "r") as f:
        logs = json.load(f)
    logs.append(log.model_dump(mode="json"))
    with open(LOGS_FILE, "w") as f:
        json.dump(logs, f, indent=4)


def get_logs() -> List[Dict[str, Any]]:
    """Return all communication logs as raw dicts (ready to serialize as JSON)."""
    _ensure_data_files()
    with open(LOGS_FILE, "r") as f:
        return json.load(f)


# =============================================================================
# SECTION 3 – TWILIO SERVICE
# Wraps the Twilio REST client to send SMS and trigger outbound phone calls.
# If credentials are missing, it returns mock SIDs so the app still runs in
# dev/test mode without a real Twilio account.
# =============================================================================

class TwilioService:
    """Handles all outbound communication via the Twilio API."""

    def __init__(self) -> None:
        self.account_sid  = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token   = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number  = os.getenv("TWILIO_PHONE_NUMBER")

        if self.account_sid and self.auth_token:
            # Real Twilio client – will make actual API calls
            self.client = Client(self.account_sid, self.auth_token)
        else:
            # Fallback for local development without credentials
            self.client = None
            print("WARNING: Twilio credentials not set. Running in mock mode.")

    def send_sms(self, to_number: str, message: str) -> Optional[str]:
        """
        Send an SMS to *to_number* with *message* as the body.
        Returns the Twilio message SID on success, None on failure.
        Returns a fake SID when running in mock mode.
        """
        if not self.client:
            return "MOCK_SID_SMS"  # Mock mode: pretend it worked

        try:
            msg = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=to_number,
            )
            return msg.sid
        except Exception as e:
            print(f"Error sending SMS: {e}")
            return None

    def make_call(self, to_number: str, message: str) -> Optional[str]:
        """
        Trigger an outbound phone call to *to_number*.
        The call uses TwiML to speak *message* twice (with a brief pause in
        between) so the recipient doesn't miss the content.
        Returns the Twilio call SID on success, None on failure.
        """
        if not self.client:
            return "MOCK_SID_CALL"  # Mock mode: pretend it worked

        # Build TwiML: pause 2 s → say message → pause 1 s → repeat message
        twiml = (
            "<Response>"
            "<Pause length=\"2\"/>"
            f"<Say voice=\"alice\">{message}</Say>"
            "<Pause length=\"1\"/>"
            f"<Say voice=\"alice\">I repeat: {message}</Say>"
            "</Response>"
        )

        try:
            call = self.client.calls.create(
                twiml=twiml,
                from_=self.from_number,
                to=to_number,
            )
            return call.sid
        except Exception as e:
            print(f"Error making call: {e}")
            return None


# Module-level singleton – imported and used by the Orchestrator
twilio_service = TwilioService()


# =============================================================================
# SECTION 4 – ORCHESTRATOR
# Parses a free-text command, identifies the target user and action type,
# then dispatches to the appropriate Twilio handler.
#
# Parsing strategy:
#   1. Scan the command for any registered username (case-insensitive).
#   2. If "message", "sms", or "text" is present → SMS; otherwise → call.
#   3. Pass the entire command as the spoken/sent message.
# =============================================================================

class Orchestrator:
    """Interprets natural-language commands and dispatches calls or SMS."""

    def __init__(self) -> None:
        # Map action names to their handler coroutines
        self.tools = {
            "call":   self._handle_call,
            "sms":    self._handle_sms,
            "status": self._handle_status,
        }

    async def process_command(self, command: str) -> Dict[str, Any]:
        """
        Entry point for the /api/process-command endpoint.
        Returns a dict with at least {"success": bool, "message": str}.
        """
        command_lower = command.lower()

        # Step 1 – Find a registered user mentioned in the command
        target_user = None
        for user in get_users():
            if user.username.lower() in command_lower:
                target_user = user
                break

        if not target_user:
            return {
                "success": False,
                "message": "Could not identify a registered recipient in your command.",
            }

        # Step 2 – Decide whether this is a call or an SMS
        action = "sms" if any(kw in command_lower for kw in ["message", "sms", "text"]) else "call"

        # Step 3 – Use the full command as the message content
        return await self.tools[action](target_user, command)

    # ------------------------------------------------------------------
    # Private action handlers
    # ------------------------------------------------------------------

    async def _handle_call(self, user: User, message: str) -> Dict[str, Any]:
        """Trigger an outbound call and log the result."""
        sid    = twilio_service.make_call(user.phone_number, message)
        status = "success" if sid else "failed"

        log = CommunicationLog(
            recipient_name=user.username,
            recipient_phone=user.phone_number,
            action="call",
            message=message,
            status=status,
            sid=sid,
        )
        add_log(log)

        return {
            "success": status == "success",
            "message": f"Call triggered for {user.username}.",
            "sid":     sid,
            "details": log.model_dump(mode="json"),
        }

    async def _handle_sms(self, user: User, message: str) -> Dict[str, Any]:
        """Send an SMS and log the result."""
        sid    = twilio_service.send_sms(user.phone_number, message)
        status = "success" if sid else "failed"

        log = CommunicationLog(
            recipient_name=user.username,
            recipient_phone=user.phone_number,
            action="sms",
            message=message,
            status=status,
            sid=sid,
        )
        add_log(log)

        return {
            "success": status == "success",
            "message": f"SMS sent to {user.username}.",
            "sid":     sid,
            "details": log.model_dump(mode="json"),
        }

    async def _handle_status(self, user: User, message: str) -> Dict[str, Any]:
        """Return basic registration info for the identified user (no Twilio call)."""
        return {
            "success": True,
            "message": f"User {user.username} is registered with number {user.phone_number}.",
        }


# Module-level singleton used by the API routes
orchestrator = Orchestrator()


# =============================================================================
# SECTION 5 – FASTAPI APPLICATION & ROUTES
# =============================================================================

app = FastAPI(title="AI Communication Platform")

# Allow all origins in development. In production, replace "*" with your
# frontend's actual domain (e.g. "https://myapp.example.com").
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Root health-check endpoint
# ------------------------------------------------------------------

@app.get("/")
async def root():
    """Simple liveness check – returns a welcome message."""
    return {"message": "Welcome to AI Communication Platform API"}


# ------------------------------------------------------------------
# User management endpoints  (prefix: /api/users)
# ------------------------------------------------------------------

@app.get("/api/users", response_model=List[User])
async def get_users_endpoint():
    """Return all registered users."""
    return get_users()


@app.post("/api/users", response_model=User)
async def create_user(user_in: UserCreate):
    """
    Register a new user.
    Returns 400 if the username is already taken (case-insensitive).
    """
    users = get_users()

    # Reject duplicate usernames to keep command parsing unambiguous
    if any(u.username.lower() == user_in.username.lower() for u in users):
        raise HTTPException(status_code=400, detail="Username already exists")

    new_user = User(username=user_in.username, phone_number=user_in.phone_number)
    users.append(new_user)
    save_users(users)
    return new_user


@app.put("/api/users/{user_id}", response_model=User)
async def update_user(user_id: str, user_in: UserUpdate):
    """
    Update an existing user's username and/or phone number.
    Returns 404 if the user_id is not found.
    """
    users = get_users()
    for i, u in enumerate(users):
        if u.id == user_id:
            updated_user = u.model_copy(update=user_in.model_dump(exclude_unset=True))
            users[i] = updated_user
            save_users(users)
            return updated_user
    raise HTTPException(status_code=404, detail="User not found")


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str):
    """Remove a user from the registry (does not delete their logs)."""
    users = get_users()
    save_users([u for u in users if u.id != user_id])
    return {"message": "User deleted"}


# ------------------------------------------------------------------
# Communication endpoints  (prefix: /api)
# ------------------------------------------------------------------

@app.post("/api/process-command")
async def process_command(request: CommandRequest):
    """
    Accept a natural-language command and execute the implied action.

    Examples:
      {"command": "Call Alice"}
        → triggers an outbound call to Alice's registered number

      {"command": "Text Bob: meeting at 3pm"}
        → sends an SMS to Bob

    Returns a result dict including success status, Twilio SID, and a log entry.
    """
    return await orchestrator.process_command(request.command)


@app.get("/api/logs")
async def get_logs_endpoint():
    """Return all communication logs (calls and SMS) in reverse-insertion order."""
    return get_logs()


# =============================================================================
# SECTION 6 – ENTRY POINT
# Run with:  python phonecall_twilio_app.py
# Or via uvicorn directly:  uvicorn phonecall_twilio_app:app --reload
# =============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("phonecall_twilio_app:app", host=host, port=port, reload=True)
