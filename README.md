# Wazobia Call Backend

FastAPI backend for Wazobia Call, including account authentication and LiveKit calling.

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

The API LOCALY is available at <http://127.0.0.1:8000>; interactive API docs are at
<http://127.0.0.1:8000/docs>.

# Website
--- https://wazobia-website-ten.vercel.app/ 
To download the apk file