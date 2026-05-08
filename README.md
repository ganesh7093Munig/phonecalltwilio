# AI Communication Platform — Twilio Phone Call & SMS

A single-file FastAPI backend that lets you trigger **outbound phone calls** and **SMS messages** to registered contacts using plain natural-language commands like *"Call Alice"* or *"Text Bob: meeting at 3pm"*.

---

## Features

- **Natural-language command parsing** — no rigid syntax required
- **Outbound phone calls** via Twilio (text-to-speech with Alice voice)
- **SMS messaging** via Twilio
- **User registry** — CRUD API to manage contacts and their phone numbers
- **Communication logs** — every call and SMS is recorded to a JSON file
- **Mock mode** — works without real Twilio credentials (returns fake SIDs)
- **Zero database setup** — data is stored in plain JSON files

---

## Project Structure

```
phonecall_twilio_app.py   ← entire backend in one file
requirements.txt          ← Python dependencies
.env                      ← your Twilio credentials (create this yourself)
data/
  users.json              ← registered contacts (auto-created)
  logs.json               ← communication history (auto-created)
```

---

## Quick Start

### 1. Clone / download the project

```bash
git clone <your-repo-url>
cd <project-folder>
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the same directory as `phonecall_twilio_app.py`:

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX

PORT=8000
HOST=0.0.0.0
```

> **Where to find your credentials:**  
> Log in to [console.twilio.com](https://console.twilio.com) → your Account SID and Auth Token are on the dashboard. The phone number is any Twilio number you have purchased.

### 5. Run the server

```bash
python phonecall_twilio_app.py
```

Or directly with uvicorn:

```bash
uvicorn phonecall_twilio_app:app --reload
```

The API will be available at `http://localhost:8000`.  
Interactive docs (Swagger UI) at `http://localhost:8000/docs`.

---

## API Reference

### Health Check

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/`      | Returns a welcome message |

---

### User Management — `/api/users`

#### Get all users
```http
GET /api/users
```
**Response:**
```json
[
  { "id": "uuid", "username": "Alice", "phone_number": "+14155552671" }
]
```

#### Create a user
```http
POST /api/users
Content-Type: application/json

{ "username": "Alice", "phone_number": "+14155552671" }
```
Returns `400` if the username already exists.

#### Update a user
```http
PUT /api/users/{user_id}
Content-Type: application/json

{ "phone_number": "+14155559999" }
```
All fields are optional — only the provided fields are updated.

#### Delete a user
```http
DELETE /api/users/{user_id}
```

---

### Send a Command — `/api/process-command`

```http
POST /api/process-command
Content-Type: application/json

{ "command": "Call Alice and tell her the meeting starts now" }
```

**How the command is parsed:**

1. The command is scanned for any registered username (case-insensitive).
2. If the words **message**, **sms**, or **text** appear → SMS is sent; otherwise → a call is placed.
3. The entire command string is used as the spoken/sent message.

**Response:**
```json
{
  "success": true,
  "message": "Call triggered for Alice.",
  "sid": "CAxxxxxxxxxxxx",
  "details": {
    "id": "uuid",
    "timestamp": "2024-01-15T10:30:00",
    "recipient_name": "Alice",
    "recipient_phone": "+14155552671",
    "action": "call",
    "message": "Call Alice and tell her the meeting starts now",
    "status": "success",
    "sid": "CAxxxxxxxxxxxx"
  }
}
```

**Command examples:**

| Command | Action |
|---------|--------|
| `"Call Alice"` | Phone call to Alice |
| `"Call Bob and say the server is down"` | Phone call to Bob |
| `"Text Alice: your package has arrived"` | SMS to Alice |
| `"Send a message to Bob about the deadline"` | SMS to Bob |

---

### Communication Logs — `/api/logs`

```http
GET /api/logs
```

Returns the full history of all calls and SMS messages as a JSON array.

---

## Running Without Twilio Credentials (Mock Mode)

If `TWILIO_ACCOUNT_SID` or `TWILIO_AUTH_TOKEN` are not set, the app starts in **mock mode**. All calls and SMS requests succeed immediately and return fake SIDs (`MOCK_SID_CALL` / `MOCK_SID_SMS`). This is useful for local development and testing without consuming Twilio credits.

A warning is printed to the console:
```
WARNING: Twilio credentials not set. Running in mock mode.
```

---

## How the Call Works

When a call is placed, the platform uses [TwiML](https://www.twilio.com/docs/voice/twiml) to instruct Twilio to:

1. Pause for 2 seconds (gives the recipient time to say hello)
2. Speak the message using Twilio's `alice` voice
3. Pause for 1 second
4. Repeat the message once more so nothing is missed

```xml
<Response>
  <Pause length="2"/>
  <Say voice="alice">Your message here</Say>
  <Pause length="1"/>
  <Say voice="alice">I repeat: Your message here</Say>
</Response>
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | 0.109.0 | Web framework |
| uvicorn | 0.27.0  | ASGI server |
| twilio  | 8.11.0  | Twilio REST client |
| python-dotenv | 1.0.0 | Load `.env` files |
| pydantic | 2.5.3 | Data validation |
| pydantic-settings | 2.1.0 | Settings management |
| python-multipart | 0.0.6 | Form data support |

---

## Notes

- Phone numbers must be in **E.164 format** (e.g. `+14155552671`).
- The Twilio "from" number must be a verified Twilio number in your account.
- If you are on a Twilio trial account, you can only call/text **verified** numbers.
- The `data/` folder is created automatically on first run — no manual setup needed.
- For production, replace `allow_origins=["*"]` in the CORS config with your actual frontend domain.
