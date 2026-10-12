# Wazobia Call — Technical Documentation

> Real-time, in-call voice translation for Nigerian languages (Yoruba, Igbo, Hausa, Nigerian Pidgin, and English).

This document is the complete technical reference for the **Wazobia Call** codebase. It covers the two sub-projects that make up the system:

- [`calltranscribe/`](calltranscribe) — the React Native / Expo **mobile app** (TypeScript).
- [`wazobiacall_backend/`](wazobiacall_backend) — the FastAPI **backend** (Python).

---

## 1. System Overview

Wazobia Call lets two people hold a normal voice call while each party hears the other in **their own preferred language**. A caller who speaks Yoruba can call a caller who speaks Igbo; the backend transcribes each side's speech, translates it into the other side's language, and the receiving phone both **displays** the translation as live captions and **speaks** it aloud via text-to-speech.

The architecture has four moving parts:

1. **Mobile app** — dials/receives calls over WebRTC (LiveKit), renders captions, plays translated speech.
2. **Backend (FastAPI)** — authentication, call signalling, and orchestration.
3. **LiveKit Cloud** — the WebRTC media plane that carries the actual audio between the two phones.
4. **External AI services** — per-language Whisper speech-to-text (Hugging Face models), the NTLAS translation engine, and the 9jaLingo TTS engine.

```
┌──────────────┐  HTTPS (REST + JWT)   ┌───────────────────────┐
│  Mobile app   │ ─────────────────────▶│  FastAPI backend       │
│  (Expo/RN)    │ ◀─────────────────────│  (call orchestration)  │
└──────┬───────┘    WS signalling       └──────────┬────────────┘
       │ WebRTC audio                             │ LiveKit SDK
       │ (LiveKit)                                 │  + STT bot
       ▼                                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     LiveKit Cloud (media)                    │
└─────────────────────────────────────────────────────────────┘
                          ▲            ▲
                          │            │
                  ┌───────┴───┐   ┌────┴───────┐
                  │  NTLAS    │   │ 9jaLingo   │
                  │ translate │   │   TTS      │
                  └───────────┘   └────────────┘
```

---

## 2. Technology Stack

| Layer | Technology |
|-------|-----------|
| Mobile framework | Expo SDK 57, React Native 0.86.3, React 19.2.3 |
| Mobile language | TypeScript |
| Routing | `expo-router` (file-based routing) |
| Styling | NativeWind v4 (Tailwind CSS) |
| WebRTC / media | `livekit-client`, `@livekit/react-native`, `@livekit/react-native-webrtc` |
| Notifications | `expo-notifications` (sticky call & incoming-call notifications) |
| Secure storage | `expo-secure-store` |
| Audio playback | `expo-audio`, `expo-file-system` |
| HTTP client | `axios` |
| Backend framework | FastAPI 0.135.x |
| ORM / DB | SQLAlchemy 2.0 + PostgreSQL (SQLite also supported for dev) |
| Auth | JWT (python-jose), bcrypt password hashing |
| Migrations | Alembic |
| STT | Hugging Face `transformers` Whisper (per-language models) |
| Translation | NTLAS engine over HTTP (configurable) |
| SMS | Termii (`apis/termii.py`) |
| LiveKit server SDK | `livekit` + `livekit-agents` |
| Server / container | Uvicorn, Docker (Python 3.11 slim) |

---

## 3. Repository Structure

```
NTLAS-Hackathon/
├── calltranscribe/                 # Expo mobile app
│   ├── app.json                    # Expo config, permissions, plugins
│   ├── package.json
│   ├── src/
│   │   ├── app/                    # expo-router screens
│   │   │   ├── _layout.tsx         # root layout (providers + stack)
│   │   │   ├── index.tsx           # startup auth gate / splash
│   │   │   ├── (auth)/
│   │   │   │   ├── _layout.tsx
│   │   │   │   ├── signin.tsx
│   │   │   │   ├── signup.tsx
│   │   │   │   └── verify.tsx      # phone verification
│   │   │   └── home/
│   │   │       ├── _layout.tsx     # bottom tabs + active-call banner
│   │   │       ├── recentcalls.tsx # call log + dialer
│   │   │       ├── contact.tsx     # contacts list
│   │   │       ├── detail.tsx      # contact/call detail
│   │   │       └── call.tsx        # in-call route
│   │   ├── components/
│   │   │   ├── call_context.tsx          # call state machine (LiveKit)
│   │   │   ├── incoming_call_context.tsx # signalling WebSocket + incoming calls
│   │   │   ├── call_screen.tsx           # in-call UI (captions + TTS)
│   │   │   ├── active_call_banner.tsx
│   │   │   ├── incoming_call_banner.tsx
│   │   │   ├── call_button.tsx
│   │   │   ├── profile_sheet.tsx         # language picker
│   │   │   └── translatebubble.tsx       # placeholder stub
│   │   └── utils/
│   │       ├── endpoint.ts        # axios client + token persistence
│   │       ├── auth.ts            # auth API calls
│   │       ├── livekit.ts         # LiveKit setup + call API calls
│   │       ├── speak.ts           # 9jaLingo TTS
│   │       └── contacts_data.ts   # (empty)
│   └── assets/
└── wazobiacall_backend/            # FastAPI backend
    ├── main.py                     # FastAPI app + CORS + routers
    ├── requirements.txt
    ├── dockerfile
    ├── alembic/                    # DB migrations
    ├── alembic.ini
    ├── apis/
    │   ├── termii.py               # Termii SMS client
    │   ├── auth/                   # auth + verify routers
    │   ├── call/                   # VOIP call pipeline
    │   └── translation/            # legacy Twilio experiments
    ├── models/                     # SQLAlchemy models
    ├── schemas/                    # Pydantic request/response models
    ├── config/dbConfig.py          # settings + DB URL assembly
    ├── tests/                      # unit tests
    └── wazobiacall/                # Python virtualenv (not source)
```

---

## 4. Backend Deep Dive (`wazobiacall_backend`)

### 4.1 Application bootstrap — [`main.py`](wazobiacall_backend/main.py)

- Creates the FastAPI app instance named `call`, with title `"Call API"`.
- Loads `.env` via `python-dotenv`.
- Includes two routers:
  - `authentication` (prefix `/auth`) — from [`apis/auth/__init__.py`](wazobiacall_backend/apis/auth/__init__.py).
  - `calls` (prefix `/voip_call`) — from [`apis/call/__init__.py`](wazobiacall_backend/apis/call/__init__.py).
- A third router, `call_translate` (Twilio-based), is commented out.
- Configures **CORS** with a permissive `allow_origins` list (includes `"*"`, localhost, and a `HOST_FRONTEND_LINK` env var), and allows all methods/headers with credentials.
- Registers a custom `RequestValidationError` handler that reshapes FastAPI's default 422 body into the app's canonical `{ status, message, errors }` shape.
- Exposes `GET /` as a health/welcome route.

### 4.2 Database & models

**Engine** — [`models/sessions.py`](wazobiacall_backend/models/sessions.py)

- Builds the `DATABASE_URL` from [`config/dbConfig.py`](wazobiacall_backend/config/dbConfig.py) `Settings`.
- If the URL starts with `sqlite`, uses `check_same_thread: False`; otherwise uses the default (PostgreSQL) engine.
- Provides the `get_db()` dependency (yields a session, closes it in a `finally`).

**Settings** — [`config/dbConfig.py`](wazobiacall_backend/config/dbConfig.py)

- `pydantic-settings` `BaseSettings`, case-sensitive, reads `.env`, `extra="allow"`.
- `assemble_db_connection()` returns `SQLALCHEMY_DATABASE_URI` if set, otherwise builds a PostgreSQL DSN from `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_DATABASE`.

**Models**

- [`models/base.py`](wazobiacall_backend/models/base.py) — `TimeStampedModel` base class with a UTC `created_at` timestamp column (server default `now()`).
- [`models/account.py`](wazobiacall_backend/models/account.py) — the `Account` model, table `users`:

| Column | Type | Notes |
|--------|------|-------|
| `userID` | String(225) | Primary key (e.g. `USER_xxxxxxxx`) |
| `username` | String(50) | Unique, non-null |
| `email` | String(255) | Unique, non-null |
| `password` | String(255) | bcrypt hash |
| `phone_number` | String(20) | Non-null |
| `verified_number` | Boolean | default `False` |
| `prefer_lang` | String(10) | non-null; STT source language |
| `created_at` | Date | server default `now()` |

**Migrations** (Alembic, [`alembic/versions/`](wazobiacall_backend/alembic/versions))

- `4a8e46c307ba_auth_tables.py` — creates the `users` table.
- `ad3a841f8f0f_correction_on_the_users_table.py` — alters `userID` to `String(225)`.

### 4.3 Authentication — [`apis/auth/auth_.py`](wazobiacall_backend/apis/auth/auth_.py)

- **JWT**: `create_access_token()` signs a payload with `SECRET_KEY` / `ALGORITHM` from the environment (`python-jose`), expiry default 12 hours.
- **`get_current_user`**: OAuth2 bearer dependency that decodes the token, reads `sub` (the `userID`), and loads the `Account`; raises 401 on failure.
- **Account ID**: `generate_account_id()` produces `USER_` + 8 hex chars.
- **Verification codes**: `pending_verification_codes` is an in-memory `dict[user_id, code]`; `verification_code_generator()` produces a 6-digit code.

Endpoints (all under `/auth`):

| Method | Path | Body | Notes |
|--------|------|------|-------|
| POST | `/auth/signup` | `AccountCreate` | bcrypt-hashes password, rejects duplicate email, returns 201 |
| POST | `/auth/signin` | `AccountSignin` | verifies bcrypt, returns JWT + `phone_verified` + `prefer_lang` |
| GET | `/auth/me` | — | returns the signed-in user's profile |
| POST | `/auth/prefer_lang` | `{ prefer_lang }` | updates the user's preferred language |
| DELETE | `/auth/delete_account` | `userMail` (query) | deletes by email |

> Note: `signin` returns some responses as `(payload, status)` tuples which FastAPI serializes as JSON arrays (e.g. `[{...}, 404]`). The frontend normalizes this — see §5.6.

### 4.4 Phone verification — [`apis/auth/verify.py`](wazobiacall_backend/apis/auth/verify.py)

- `POST /auth/verify-number` accepts an optional `{ code }` body:
  - **No code / `"0"`** → generates and "sends" a new code. SMS delivery via Termii is currently **disabled**; the code is printed to server logs and stored in memory.
  - **With code** → validates against the stored code; on success sets `verified_number=True`.

### 4.5 Call pipeline — [`apis/call/voipcall.py`](wazobiacall_backend/apis/call/voipcall.py)

This is the heart of the backend. Key concepts:

- **In-memory call registry**: `calls: dict[room, info]` where `info` holds `caller`, `callee`, and `created_at`.
- **`transcription_tasks`**: per-room asyncio task running the STT bot.
- **Room capacity**: `MAX_ROOM_PARTICIPANTS = 3` (two callers + one hidden bot).
- **`Hub`**: fan-out of events to WebSocket clients keyed by phone identity (supports multiple sockets per identity).
- **`normalize_phone()`**: normalizes numbers to E.164 (`+234…`) so caller/callee identities match across the system.

**Language mapping** (`LANGUAGE_CODES` / `STT_LANGUAGE_CODES`):

| Preferred language | STT code |
|--------------------|----------|
| english | `en` |
| yoruba | `yo` |
| igbo | `ig` |
| hausa | `ha` |
| nigerian pidgin / pidgin | `pcm` |

Anything else falls back to `en`.

**`start_transcription()`** launches the bot and defines `publish_transcript()`:

1. Receives an STT result for a speaker, in that speaker's language.
2. Determines the **listener** (the other party) and the **target language**.
3. Calls `translate()` (NTLAS) to translate into the listener's language.
4. Sends a `transcription` event to the listener only (never echoes a speaker's own words back).
5. For **final** utterances, additionally sends a `translation` event (used by the app to speak the text aloud).

Endpoints (all under `/voip_call`):

| Method | Path | Description |
|--------|------|-------------|
| WS | `/voip_call/ws/{identity}` | signalling socket; the app registers its phone number to receive events |
| POST | `/voip_call/call` | start an outgoing call |
| POST | `/voip_call/call/{room}/accept` | callee accepts, receives a LiveKit token |
| POST | `/voip_call/call/{room}/decline` | decline an incoming call |
| POST | `/voip_call/call/{room}/end` | end an active call |

**`start_call` flow**:

1. Normalizes caller/callee, checks both aren't already in a call (409 `you_are_busy` / `line_busy`).
2. Looks up the callee in the `users` table (using phone variants). If **not registered**, sends an SMS invitation via Termii and returns `invitation_sent: true`.
3. Creates a LiveKit room (`call-` + 10 hex chars), resolves both parties' STT models from `prefer_lang`.
4. Records the call, starts transcription, and preloads the two selected STT models in the background (without delaying ringing).
5. Sends an `incoming_call` event to the callee over the hub.
6. Returns `{ room, token }` (a LiveKit access token for the caller).

**Call lifecycle / resilience**: `find_busy_room()`, `_room_has_callers()`, `_delete_room()`, and `drop_call()` together ensure a call has **no time limit** and that a number is released when its LiveKit room no longer holds a real participant (handles abnormal disconnects that never reach `/end`). Room checks "fail safe" (report active) if LiveKit is unreachable.

### 4.6 Speech-to-text — [`apis/call/providers.py`](wazobiacall_backend/apis/call/providers.py)

- **Lazy per-language Whisper models**: nothing loads at import time. Each language has its own `model_id`, and only the selected language's weights are ever downloaded/cached (in `_MODEL_CACHE`, guarded by a lock).
- Device resolution picks **CUDA if available, otherwise CPU**.
- `BaseChunkedSTT` implements **energy-based utterance segmentation** on top of the non-streaming Whisper model:
  - `SPEECH_THRESHOLD`, `PRE_ROLL_MS` (200), `SILENCE_MS` (700), `MAX_UTTERANCE_MS` (12s), `MIN_SPEECH_MS` (400).
  - Buffers audio, replays pre-roll so the first syllable isn't clipped, and flushes an utterance on silence or the hard cut.
  - Transcription runs in a worker thread (`asyncio.to_thread`) so the event loop stays free; results are ordered through an asyncio lock/queue.
- **`STTResult`** carries `text` and `is_final`.

Per-language classes (Hugging Face repo IDs):

| Language | Class | Model |
|----------|-------|-------|
| Yoruba | `YorubaSTT` | `NCAIR1/Yoruba-ASR` |
| Igbo | `IgboSTT` | `NCAIR1/Igbo-ASR` |
| Hausa | `HausaSTT` | `NCAIR1/Hausa-ASR` |
| English | `EnglishSTT` | `NCAIR1/NigerianAccentedEnglish` |
| Pidgin | `PidginSTT` | reuses the Nigerian-accented English model (documented limitation) |

- `STT_REGISTRY` maps codes → classes; `make_stt(lang)` is the factory; `preload()` warms up only the requested languages.

### 4.7 Translation — [`apis/call/translation.py`](wazobiacall_backend/apis/call/translation.py)

- The single seam the call pipeline uses. Translation is delegated to the external **NTLAS** engine.
- Configured via `NTLAS_TRANSLATE_URL`; if unset, text **passes through unchanged** (calls still work, just untranslated).
- Call contract: `POST <url>` with `{ "text", "source", "target" }`; accepts either `{ "translated" }` or `{ "text" }` in the response.
- 10-second timeout; any engine failure logs and falls back to the original text so a live call is never broken.

### 4.8 Text-to-speech — [`apis/call/tts.py`](wazobiacall_backend/apis/call/tts.py)

- Mirrors the STT layout (base class + one class per language + registry + `make_tts` factory).
- **Currently a stub**: every `synthesize()` returns `None`. The voice provider is not yet chosen.
- Note: in the live product, TTS is performed **on the phone** via 9jaLingo (see §5.7), not on the backend.

### 4.9 Hidden transcription bot — [`apis/call/voidBot.py`](wazobiacall_backend/apis/call/voidBot.py)

- Joins each LiveKit call as a **hidden** participant (`identity = transcriber-<room>`, `hidden=True`, can subscribe but not publish).
- Requires `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
- On `track_subscribed` for audio tracks, opens an `rtc.AudioStream` (16 kHz mono PCM16) and feeds frames into the STT session; forwards results via the `on_transcript` callback.
- Exits when the last remote participant leaves or after `max_seconds` (900s default).

### 4.10 SMS — [`apis/termii.py`](wazobiacall_backend/apis/termii.py)

- Sends SMS through **Termii** (`POST <base>/api/sms/send`).
- Requires `TERMII_BASE_URL`, `TERMII_API_KEY`, `TERMII_SENDER_ID`; raises 503 if unconfigured, 502 on upstream failure.
- Helpers: `send_verification_code()` and `send_invitation()` (invite non-registered numbers to install the app).
- [`apis/call/termii.py`](wazobiacall_backend/apis/call/termii.py) is a thin wrapper re-exporting `send_invitation`.

### 4.11 Legacy Twilio experiments — [`apis/translation/`](wazobiacall_backend/apis/translation)

- [`makecall.py`](wazobiacall_backend/apis/translation/makecall.py) and [`translate.py`](wazobiacall_backend/apis/translation/translate.py) contain Twilio-based PSTN/Twiml/media-stream experiments. **Not registered in `main.py`** (the `call_translate` include is commented out). Keep these as reference only.

---

## 5. Frontend Deep Dive (`calltranscribe`)

### 5.1 Entry & providers

- [`src/app/_layout.tsx`](calltranscribe/src/app/_layout.tsx) — the root layout. Wraps the app in `<CallProvider>` → `<IncomingCallProvider>` → `<Stack>` (with `index`, `(auth)`, and `home` screens, all headers hidden). Imports global Tailwind styles.
- [`src/app/index.tsx`](calltranscribe/src/app/index.tsx) — startup gate: loads the persisted token, and routes to sign-in if missing, or validates it against `/auth/me` and routes to `/home/recentcalls` if valid.

### 5.2 Screens & navigation

| Route | File | Purpose |
|-------|------|---------|
| `/` | `index.tsx` | splash / auth gate |
| `/(auth)/signin` | `signin.tsx` | email + password sign-in |
| `/(auth)/signup` | `signup.tsx` | account creation |
| `/(auth)/verify` | `verify.tsx` | phone verification (code entry + resend countdown) |
| `/home` | `_layout.tsx` | bottom tabs (`Calls`, `Contacts`) + `ActiveCallBanner` |
| `/home/recentcalls` | `recentcalls.tsx` | call log + dialer modal |
| `/home/contact` | `contact.tsx` | contacts list (device contacts or fallback) |
| `/home/detail` | `detail.tsx` | contact detail + call button |
| `/home/call` | `call.tsx` | in-call screen wrapper |

Navigation flow: **sign in → verify (if needed) → Calls tab → contact/detail or dialer → call screen**.

### 5.3 Call state — [`call_context.tsx`](calltranscribe/src/components/call_context.tsx)

`CallProvider` is the central call state machine. Exposed via `useCall()`:

| Value | Type | Description |
|-------|------|-------------|
| `activeCall` | `ActiveCall \| null` | current call (`name`, `number`, `room`, `direction`, `startedAt`, `connectedAt`) |
| `elapsedSeconds` | number | ticks only after both parties connect |
| `isConnected` | boolean | true once `connectedAt` is set |
| `isMuted` / `isSpeaker` | boolean | mute & speaker state |
| `callNotice` | string \| null | transient failure message |
| `livekitState` | `"connected" \| "reconnecting" \| null` | LiveKit link state |
| `startCall(name, number)` | fn | initiate an outgoing call |
| `answerCall(name, number, room, token)` | fn | join an incoming call |
| `endCall()` | fn | hang up (best-effort teardown, always routes home) |
| `endCallWithNotice(msg)` | fn | show notice then hang up |
| `toggleMute()` / `toggleSpeaker()` | fn | mic / audio-output controls |

Key behaviours:

- **`joinRoom`** — creates a `livekit-client` `Room`, wires `ParticipantConnected`/`ParticipantDisconnected`/`Reconnecting`/`Reconnected`/`Disconnected` events, pre-warms the connection, starts the platform audio session, connects with 30s timeouts, and enables the mic. The call timer starts only when both parties are in the room; a remote leave ends the call.
- **Network-failure detection** — `isNetworkFailure()` + `NETWORK_DISCONNECT_REASONS` distinguish genuine link failures from normal hang-ups; an 8-second reconnect grace is applied before "Poor network".
- **Notifications** — sets up channels (`Ongoing call`, `Incoming calls`) and categories with **Answer / Decline / Hang up** action buttons; sticky foreground notifications mirror the call lifecycle.
- **`stopMic`** — releases the mic with a 1.5s timeout budget, disconnects the room, stops the audio session; never blocks on teardown.

### 5.4 Incoming-call signalling — [`incoming_call_context.tsx`](calltranscribe/src/components/incoming_call_context.tsx)

`IncomingCallProvider` manages the **signalling WebSocket**:

- Converts the HTTP(S) backend URL to a WebSocket URL and connects to `/voip_call/ws/{phone}` using the signed-in user's phone number as identity.
- Sends a `ping` heartbeat every 25s; reconnects with exponential backoff (capped at 30s) on close.
- Dispatches incoming server events:

| Event | Action |
|-------|--------|
| `incoming_call` | set `incomingCall`, show the incoming-call notification |
| `transcription` | forward a `TranscriptEvent` to caption subscribers |
| `translation` | forward a `TtsEvent` (spoken aloud, never rendered) |
| `state` | forward a state event (handled, though the backend does not currently emit it) |
| `call_declined` | show "Rejected" notice and hang up (if caller) |
| `call_ended` / `call_cancelled` | hang up |

- Exposes `subscribeTts(listener)` and `subscribeTranscript(listener)` subscription APIs used by the call screen.
- Handles **Answer/Decline** from both the in-app banner and native notification actions (with deduping to prevent double-processing).

### 5.5 In-call screen — [`call_screen.tsx`](calltranscribe/src/components/call_screen.tsx)

- Shows caller info, a **live translator panel** (renders the other party's speech in *your* language — the backend already places the translated text in the `translated` field).
- A **TTS status bubble** shows fixed labels only (`Transcribing…`, `Translating…`, `Speaking…`, etc.); the spoken/original text is never rendered in the bubble.
- A serialized **TTS queue** (`queueRef`) plays each `translation` event through 9jaLingo one at a time, advancing on `playbackStatusUpdate.didJustFinish`.
- Caption logic collapses interim (non-final) lines into a single live line and keeps only the last 3 lines.
- Mute / speaker / hang-up controls. A dev-only "Test TTS" button is shown under `__DEV__`.

### 5.6 HTTP & auth utilities — [`endpoint.ts`](calltranscribe/src/utils/endpoint.ts) and [`auth.ts`](calltranscribe/src/utils/auth.ts)

- `endpoint.ts`:
  - `BACKEND_URL` defaults to a ngrok tunnel (`https://skied-custody-shrouded.ngrok-free.dev`), overridable with `EXPO_PUBLIC_BACKEND_URL`.
  - `api` is a shared axios client.
  - Token is kept in memory and persisted in `expo-secure-store` under `wazobia_auth_token`; `setAuthToken`/`getAuthToken`/`loadAuthToken` manage it, with a listener API for sign-in/out events.
  - An axios request interceptor attaches the `Bearer` token to every request.
- `auth.ts`:
  - `signup`, `signin`, `getMe`, `updatePreferredLanguage`, `requestVerificationCode`, `verifyCode`.
  - `unwrapResponse()` normalizes FastAPI's `(payload, status)` tuple (serialized as a JSON array) back to the payload object.

### 5.7 TTS — [`speak.ts`](calltranscribe/src/utils/speak.ts)

- On-device text-to-speech via **9jaLingo** (`https://api.9jalingo.org`), using `expo-file-system` + `expo-audio`.
- Per-language speaker IDs: `yo`, `ig`, `pcm`, `ha` (English omitted from the voice map).
- Handles the engine's **cold-start** flow: a `202` response returns a `job_id`, which is polled (up to 5 minutes) until `completed`.
- Writes the returned WAV to a single rotating temp file and plays it; `cleanupTts()` removes the last file.
- `warmUpTts()` runs once per app session (the Starter plan allows only 5 TTS requests/hour, so it must not burn quota).

### 5.8 Other components

- [`active_call_banner.tsx`](calltranscribe/src/components/active_call_banner.tsx) — persistent banner (top of the tab screen) while a call is active, with inline Hang up.
- [`incoming_call_banner.tsx`](calltranscribe/src/components/incoming_call_banner.tsx) — slide-down Answer/Decline banner.
- [`call_button.tsx`](calltranscribe/src/components/call_button.tsx) — round call button used in lists.
- [`profile_sheet.tsx`](calltranscribe/src/components/profile_sheet.tsx) — bottom sheet to view profile and change the preferred language (English/Yoruba/Igbo/Hausa/Nigerian Pidgin).
- [`translatebubble.tsx`](calltranscribe/src/components/translatebubble.tsx) — placeholder stub (unused).

---

## 6. API Reference

### 6.1 Authentication

#### `POST /auth/signup` → 201

```json
{ "username": "ada", "phone_number": "+2348012345678", "email": "ada@example.com", "password": "password123" }
```

Response: `{ "status": "success", "message": "Account created successfully", "account_id": "USER_xxxxxxxx" }`

#### `POST /auth/signin` → 200

```json
{ "email": "ada@example.com", "password": "password123" }
```

Response (verified): `{ "status": "successfull", "user_id": "USER_xxxxxxxx", "prefer_lang": "english", "phone_verified": true, "token": "<jwt>" }`

#### `GET /auth/me` → 200 (Bearer token required)

Response: `{ "status": "success", "user_id", "username", "email", "phone_number", "verified_number", "prefer_lang" }`

#### `POST /auth/prefer_lang` → 200 (Bearer)

```json
{ "prefer_lang": "yoruba" }
```

#### `POST /auth/verify-number` → 200 (Bearer)

- `{}` or `{ "code": "0" }` → send a new code.
- `{ "code": "123456" }` → verify.

#### `DELETE /auth/delete_account?userMail=ada@example.com` → 200

### 6.2 Calls (`/voip_call`)

#### `POST /voip_call/call` (Bearer)

```json
{ "callee": "+2348012345678" }
```

Responses:
- Success: `{ "room": "call-xxxxxxxxxx", "token": "<livekit-jwt>" }`
- Not registered: `{ "status": "successful", "invitation_sent": true, "message": "..." }`
- Busy: `409` with `detail` of `"you_are_busy"` or `"line_busy"`.

#### `POST /voip_call/call/{room}/accept` (Bearer)

```json
{ "identity": "+2348012345678" }
```

Response: `{ "token": "<livekit-jwt>" }`

#### `POST /voip_call/call/{room}/decline`

Response: `{ "ok": true }`

#### `POST /voip_call/call/{room}/end`

Response: `{ "ok": true }`

### 6.3 WebSocket signalling

`WS /voip_call/ws/{identity}` — the client connects with its phone number (E.164) and only listens; the server pushes events.

**Server → client events:**

| Event | Payload | Meaning |
|-------|---------|---------|
| `incoming_call` | `{ room, caller, caller_name }` | a call is ringing this device |
| `call_accepted` | `{ room }` | the callee answered |
| `call_declined` | `{ room }` | the callee declined |
| `call_ended` | `{ room }` | the call ended |
| `transcription` | `{ room, caller, callee, speaker, speaker_label, listener, text, translated, final, language, target_language }` | live transcript (sent to the **listener** only) |
| `translation` | `{ room, translated, lang }` | final translated utterance to be **spoken aloud** (TTS) |

---

## 7. End-to-End Call Flow

```
Caller app                 Backend                      Callee app
    │                         │                              │
    │── POST /voip_call/call ─▶│                              │
    │   (JWT + callee)        │── normalize numbers           │
    │                         │── look up callee in DB        │
    │                         │── create LiveKit room         │
    │                         │── start STT bot (voidBot)     │
    │                         │── preload STT models          │
    │◀── { room, token } ─────│── incoming_call via WS ──────▶│
    │── join LiveKit room ───▶│                              │
    │                         │◀── POST /accept (token) ──────│
    │◀── call_accepted ───────│── call_accepted via WS ──────▶│
    │                         │◀── join LiveKit room ─────────│
    │       · · · both parties connected, audio flows · · ·   │
    │                         │  bot: STT(voice A) → translate│
    │                         │  → transcription/translation   │
    │◀── transcription/translation (for B's ears) ────────────│ (B sees caption + hears TTS)
    │   (A sees caption + hears TTS of B)                     │
    │                         │◀── POST /end ─────────────────│
    │◀── call_ended ──────────│── call_ended via WS ─────────▶│
```

---

## 8. Configuration & Environment Variables

### Backend (`.env` in `wazobiacall_backend/`)

| Variable | Used by | Notes |
|----------|---------|-------|
| `SECRET_KEY`, `ALGORITHM` | auth | JWT signing |
| `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_DATABASE` | dbConfig | PostgreSQL DSN (when no `SQLALCHEMY_DATABASE_URI`) |
| `SQLALCHEMY_DATABASE_URI` | dbConfig | optional full override |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | voipcall / voidBot | LiveKit Cloud |
| `NTLAS_TRANSLATE_URL` | translation | external translation engine |
| `HF_TOKEN` | providers | Hugging Face model access |
| `TERMII_BASE_URL`, `TERMII_API_KEY`, `TERMII_SENDER_ID` | termii | SMS |
| `HOST_FRONTEND_LINK` | main | CORS allow-list |
| `TWILIO_*` | legacy makecall | unused in the live pipeline |

### Frontend (`.env` in `calltranscribe/`)

| Variable | Used by | Notes |
|----------|---------|-------|
| `EXPO_PUBLIC_BACKEND_URL` | endpoint.ts | backend base URL (defaults to ngrok) |
| `EXPO_PUBLIC_LIVEKIT_URL` | livekit.ts | LiveKit URL (defaults to LiveKit Cloud) |
| `EXPO_PUBLIC_LIVEKIT_LOG_LEVEL` | livekit.ts | LiveKit log verbosity (default silent) |
| `EXPO_PUBLIC_NAIJALINGO_KEY` | speak.ts | 9jaLingo API key |

---

## 9. Setup & Running

### Backend

```bash
cd wazobiacall_backend
python -m venv wazobiacall            # a venv already exists in ./wazobiacall
# activate it, then:
pip install -r requirements.txt
alembic upgrade head                  # apply migrations
uvicorn main:call --reload --port 8000
```

Run tests:

```bash
python -m unittest discover -s tests
```

### Mobile app

```bash
cd calltranscribe
npm install
npx expo start
# or: npx expo run:android / run:ios
```

The app uses a development build (it depends on custom native modules: LiveKit/WebRTC, foreground service, call-log). Use Expo Go only for limited flows.

---

## 10. Testing

| Test file | Coverage |
|-----------|----------|
| [`tests/test_termii_sms.py`](wazobiacall_backend/tests/test_termii_sms.py) | Termii SMS payload construction, invitation text, missing-config (503) and upstream-failure (502) handling |
| [`tests/test_stt_languages.py`](wazobiacall_backend/tests/test_stt_languages.py) | STT language code mapping / per-language model isolation |
| [`tests/test_busy_recovery.py`](wazobiacall_backend/tests/test_busy_recovery.py) | Busy-line detection and room recovery logic |

---

## 11. Deployment

- **Backend** ships a [`dockerfile`](wazobiacall_backend/dockerfile) (Python 3.11 slim, CPU-only PyTorch, Uvicorn on port 8000). The [`README.md`](wazobiacall_backend/README.md) uses a Hugging Face Space front-matter (`sdk: docker`, `app_port: 8000`).
  - ⚠️ Note a minor discrepancy: the Dockerfile `EXPOSE`s `7860` but the `CMD` runs on `8000`.
- **Mobile** uses EAS (project id `da10e9cd-a980-4a8b-b28b-eb12cd22080f` in [`app.json`](calltranscribe/app.json)); see [`eas.json`](calltranscribe/eas.json) for build profiles.

---

## 12. Known Limitations & TODOs

1. **Pidgin STT** reuses the Nigerian-accented English Whisper model — accuracy is lower than dedicated models.
2. **Backend TTS** (`apis/call/tts.py`) is stubbed; production TTS happens on-device via 9jaLingo (whose Starter plan limits requests to ~5/hour).
3. **SMS verification** is disabled in code — codes are printed to server logs instead of sent via Termii.
4. **Twilio PSTN** modules (`apis/translation/`) are legacy and not registered.
5. `Account.phone_number` is stored as plain text; the `users` table has no call-log/session persistence (call history lives on the device).
6. `delete_account` and some auth paths return ad-hoc tuples/dicts rather than the canonical `{ status, message }` envelope.

---

## 13. Security Notes

- Passwords are hashed with **bcrypt**; JWTs are signed with the server `SECRET_KEY`.
- The CORS configuration currently allows `"*"` alongside specific origins with `allow_credentials=True` — review this before production.
- The backend keeps call state and verification codes **in memory**; a restart clears both (acceptable for a hackathon/demo, but not for multi-instance production).
- Client secrets (`EXPO_PUBLIC_*`) are embedded in the app bundle and are **not** confidential.
- Sensitive values (DB password, Termii key, LiveKit secret) must be supplied via `.env` and never committed.
