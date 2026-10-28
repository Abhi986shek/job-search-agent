# One-time setup on a new machine: venv, dependencies, .env files, database.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
if (-not (Test-Path "Myenv")) { py -3.11 -m venv Myenv }
$py = Join-Path $PSScriptRoot "Myenv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt -r frontend\requirements.txt

if (-not (Test-Path "job_agent\.env")) {
    Copy-Item "job_agent\.env.example" "job_agent\.env"
    $key = & $py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    $token = & $py -c "import secrets; print(secrets.token_urlsafe(32))"
    (Get-Content "job_agent\.env") -replace '^ENCRYPTION_KEY=.*', "ENCRYPTION_KEY=$key" `
        -replace '^BACKEND_API_TOKEN=.*', "BACKEND_API_TOKEN=$token" | Set-Content "job_agent\.env" -Encoding ascii
    "JOB_AGENT_API_URL=http://127.0.0.1:8001`nJOB_AGENT_API_TOKEN=$token" | Set-Content "frontend\.env" -Encoding ascii
    Write-Host "Created job_agent\.env and frontend\.env. Add your API keys to job_agent\.env."
}

Set-Location "job_agent"
& (Join-Path $PSScriptRoot "Myenv\Scripts\alembic.exe") upgrade head
Write-Host "Setup done. Start the app with: bash run.sh"
