# Setup

This guide sets up the Job Search and CV Agent on a Windows machine. It takes about 30 minutes, most of it spent
creating accounts and API keys.

## 1. Prerequisites

| Needed | Why | Check |
|---|---|---|
| Windows 10 or 11 | Scripts are written for Windows PowerShell | |
| Python 3.11 | The backend and its packages | `py -3.11 --version` |
| Git for Windows | Provides `bash` for `run.sh` | `& "C:\Program Files\Git\bin\bash.exe" --version` |
| AWS account with Bedrock access | The AI features | Model enabled in your region |

Install Python 3.11 from python.org, or with `winget install Python.Python.3.11`. Install Git for Windows from
git-scm.com, or with `winget install Git.Git`.

Plain `bash` in PowerShell starts WSL on Windows. If WSL has no Linux distribution installed, it fails with
"execvpe(/bin/bash) failed". Always start Git Bash with the full path shown in step 5.

## 2. Get the code

```powershell
git clone <your repository URL> job-search-agent
cd job-search-agent
```

Or download the ZIP from GitHub, extract it, and open the folder.

## 3. Install

Run this once from the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

`setup.ps1` does the following:
- creates the virtual environment `Myenv` with Python 3.11,
- installs the backend and frontend packages from their exact-version `requirements.txt` files,
- creates `job_agent/.env` and `frontend/.env` from the examples, with a new encryption key and a shared backend token,
- creates the database in `data/`.

Running it again is safe. It keeps your existing `.env` files.

## 4. Add your keys

Open `job_agent/.env` in an editor and fill in the values you need. Each line is documented in
`job_agent/.env.example`. Never share these values or commit the file.

| Setting | Needed for | Where to get it |
|---|---|---|
| `AWS_PROFILE`, `AWS_REGION`, `BEDROCK_MODEL_ID` | All AI features | Your AWS CLI profile, region, and an enabled model |
| `SERPAPI_API_KEY` | Google Jobs search | serpapi.com dashboard |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Adzuna search | developer.adzuna.com |
| `PREDICTLEADS_API_KEY`, `PREDICTLEADS_API_TOKEN` | Company career-page search | predictleads.com |
| `GITHUB_PERSONAL_USERNAME`, `GITHUB_PERSONAL_TOKEN` | Your personal repos | GitHub fine-grained token, read-only |
| `GITHUB_COMPANY_ORG`, `GITHUB_COMPANY_TOKEN` | Office repos (optional) | Token approved by your organisation |
| `APIFY_TOKEN`, `LINKEDIN_PROFILE_URL` | LinkedIn profile fetch (optional) | console.apify.com |
| `APOLLO_API_KEY` | Contact search (optional) | apollo.io |
| `GMAIL_ADDRESS`, `GMAIL_OAUTH_CLIENT_FILE` | Sending and reading Gmail | See section 6 |

Keys you do not have can stay empty. That source shows "not configured" and the others still work.

Fine-grained GitHub tokens should be read-only and limited to the repos you need. For office repos, check your
company's policy before allowing content to be read.

## 5. Start the app

```powershell
& "C:\Program Files\Git\bin\bash.exe" run.sh
```

Then open:

| What | Address |
|---|---|
| App | http://localhost:8501 |
| Backend API docs | http://127.0.0.1:8001/docs |
| Backend log | `job_agent\app.log` |

Press Ctrl+C in the terminal to stop both servers. After you change `job_agent\.env`, stop and start again.

## 6. Connect Gmail (optional)

Gmail is used to send approved emails and to read replies in threads the app started.

1. In Google Cloud Console, create a project, then enable the **Gmail API**.
2. Open **Google Auth Platform**. Set the app type to **External**, then add the scopes
   `gmail.send` and `gmail.readonly`.
3. Under **Audience > Test users**, add the Gmail address you will connect. While the app is in *Testing*, only test
   users can sign in, and the sign-in expires after about 7 days.
4. Under **Clients**, create an **OAuth client ID** of type **Desktop app**, then download its JSON file.
5. Save the JSON outside the project folder, for example `C:\Users\<you>\secrets\gmail_client.json`.
6. Set `GMAIL_OAUTH_CLIENT_FILE` to that path and `GMAIL_ADDRESS` to your address in `job_agent\.env`.
7. Restart the app, open **Email and availability**, click **Connect Gmail**, and sign in with the test user.

If Google shows "Access blocked", check that the signed-in account is the test user, and that the client was created
in the same project as the test user.

## 7. Connect AWS (for the AI features)

The app calls Amazon Bedrock with the AWS profile named in `AWS_PROFILE`.

- If the profile uses AWS SSO, run `aws sso login --profile <name>` before using AI features. The login expires, and
  the AI features fail until you log in again.
- Enable the model in `BEDROCK_MODEL_ID` for your account and region under Bedrock > Model access.

## 8. First run checklist

1. **Status page:** each key you added shows as configured.
2. **Profile inputs:** upload your CV with a note, add LinkedIn data, sync GitHub and select the repos to include,
   then click **Build profile**. This is the first real call to the model.
3. **Roles:** propose or add a target role, then confirm it.
4. **Job search:** run a small search (limit 5) and check each source's status.
5. **Matches and CVs:** score a batch of jobs, approve or reject the suggested CV changes, then preview and approve
   a CV.
6. **Outreach:** create one email draft to your own address to test sending.

## 9. Move to another device

1. Copy the project folder **without** `Myenv`.
2. Copy `data\` (database, uploads, generated CVs and your photo).
3. Copy the Gmail client JSON to the same path, or update `GMAIL_OAUTH_CLIENT_FILE`.
4. Copy `job_agent\.env` and `frontend\.env` together with `data\`. The `ENCRYPTION_KEY` in `.env` is needed to read
   the saved Gmail login.
5. Use a private channel for these files. They contain keys and personal data.
6. On the new device, complete sections 1, 3 and 7, then run section 5.

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `bash` fails with "execvpe(/bin/bash) failed" | Use the full path to Git Bash shown in section 5. |
| Port 8501 or 8001 in use | Stop the other process, or change the port in the frontend and backend settings. |
| AI features fail with a token or credentials error | Run `aws sso login --profile <name>`. |
| "Model not enabled" or access denied from Bedrock | Enable the model under Bedrock > Model access. |
| Google "Access blocked" | Add the Gmail address under Audience > Test users. |
| Gmail sign-in stops working after a week | Expected in Testing mode. Click Connect Gmail again. |
| Matches or CV preview look empty after a change | Score the jobs again, or rebuild the profile. Previous results are kept per profile version. |
| Database error on startup | Migrations run automatically when the backend starts. Read the first error in `job_agent\app.log`. |

Check `job_agent\app.log` for the full error. It contains no secret values.
