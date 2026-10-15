# Wazobia Call Backend

FastAPI backend for Wazobia Call, including account authentication and LiveKit calling.

# N-ATLAS ASR transcribes speech; a separate translation service translates the text

$env.example
```
   # PostgreSQL database
   DB_USER=your_database_user
   DB_PASSWORD=replace_with_database_password
   DB_HOST=localhost
   DB_PORT=5432
   DB_DATABASE=wazobiacall

   # Authentication signing key and JWT algorithm
   # Generate a strong random key for local use; do not reuse production secrets.
   SECRET_KEY=replace_with_a_long_random_secret
   ALGORITHM=HS256

   # LiveKit project credentials (required for call endpoints)
   LIVEKIT_URL=wss://your-project.livekit.cloud
   LIVEKIT_API_KEY=replace_with_livekit_api_key
   LIVEKIT_API_SECRET=replace_with_livekit_api_secret

   # Optional: configure SMS invitations and verification
   #sms is not yet active in the backend due to verification still progress from the sms platform
   TERMII_BASE_URL=https://v3.api.termii.com
   TERMII_API_KEY=replace_with_termii_api_key
   TERMII_SENDER_ID=your_sender_id

   # Optional: translation service endpoint
   NTLAS_TRANSLATE_URL=

   # Optional: Hugging Face access token for gated speech models
   HF_TOKEN=

```

## Run locally

Requirements: Python 3.11 or newer, PostgreSQL, and a LiveKit project.

1. From this directory, create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies and create your local environment file:

   ```powershell
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

3. Edit `.env` with your PostgreSQL and LiveKit credentials. Optional integrations
   (SMS, translation, and Hugging Face) can be configured as needed.

4. Start the API from this directory:

   ```powershell
   uvicorn main:call --reload
   ```
   ```
   The API LOCALY is available at <http://127.0.0.1:8000>; interactive API docs are at
   <http://127.0.0.1:8000/docs>.
   ```

   ```
      ngrok http 8000
   ```
# Website
   ```
      https://wazobia-website-ten.vercel.app/ 
   ```
To download the apk file
