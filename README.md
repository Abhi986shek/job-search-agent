# Job Search and CV Agent

A personal, local-first assistant that helps you find jobs, tailor your CV, and prepare outreach. It reads your CV,
notes, LinkedIn data and GitHub repos, finds matching jobs, scores them against your profile, groups similar roles,
proposes CV changes per group, and drafts emails and LinkedIn messages.

You stay in control. Nothing is applied, sent or generated as a final file until you click the button for it.

- Backend: FastAPI and a Strands agent on AWS Bedrock, with SQLite storage (`job_agent/`).
- Frontend: Streamlit (`frontend/`). It talks to the backend over HTTP only.

For installation, see **[SETUP.md](SETUP.md)**.

---

## Features

- **Profile from your inputs.** Upload a CV (PDF or DOCX) with notes, add LinkedIn data (export, PDF or Apify),
  select GitHub repos (personal and office), and add manual projects. Notes override the CV. Open questions are
  shown when sources conflict or are unclear.
- **Job discovery** from several sources, de-duplicated into one list (see [Job sources](#job-sources)).
- **Scoring and grouping.** Jobs are scored against your profile, including your experience level, and grouped so
  one tailored CV can serve each group. Scoring runs in batches of open jobs.
- **Tailored CVs.** Proposed changes are shown one by one. You approve or reject each change. Then the CV is
  rendered as an HTML preview, DOCX and PDF with the same layout. You can edit the preview before approving.
- **Outreach.** Find contacts, draft emails or LinkedIn messages, refine drafts, attach the generated CV, and send
  approved emails one at a time from your Gmail. LinkedIn messages are sent by you.
- **Reply tracking.** Replies in threads the app started are read and classified, and you can draft a response.
- **Assistant.** A chat agent with read-only tools for jobs, the profile, GitHub repos and LinkedIn posts. Past
  conversations are kept.

## Hard rules

These rules are built into the code. Changing them is a deliberate decision, not a configuration option.

- The agent never approves CV changes, generates CV files, reveals Apollo emails, connects Gmail, or sends email.
  These are buttons you click.
- No scraping of job portals (Naukri, Glassdoor, Indeed and similar). Their listings come only through search APIs or
  links you save yourself. Saved links are stored, never fetched.
- No LinkedIn automation: no direct messages, connection requests or Easy Apply. Drafts only.
- Profiles, CVs and drafts use only facts from your own inputs. Nothing is invented.
- Secrets live only in `.env` files and are never printed or logged.

## Job sources

| Source | What it covers | Access |
|---|---|---|
| PredictLeads (REST) | Company career pages and ATS feeds, by O*NET code | API key and token |
| SerpApi Google Jobs | Listings Google indexes, including some portals (partial coverage) | API key |
| Adzuna | Aggregated job ads for a country | Free developer key |
| freehire public API | ATS boards and aggregators, including some portal listings | Public, no key |
| ATS boards | Greenhouse, Lever and Ashby company boards you add | Public, no key |
| Saved links | Links you found yourself. Stored, never fetched | None |

## Architecture

```
frontend/              Streamlit pages (Profile, Roles, Search, Jobs, Matches and CVs, Outreach, Assistant, ...)
job_agent/
  app.py               FastAPI entry point, token check, background reply checker
  routes.py            HTTP routes (thin: validate, call a service, return)
  agent.py             Assistant agent (Strands, Bedrock) and its chat sessions
  prompts.py           System prompts for the assistant, profile building and drafting
  llm.py               The one place that creates Bedrock model calls
  cv_render.py         CV layout: HTML preview, DOCX and PDF from one structure
  clients/             Every third-party HTTP call (job sources, GitHub, Apify, Apollo, Gmail, SMTP)
  services/            Business logic (search, profile, matching, CVs, outreach, repo and LinkedIn readers)
  db/                  SQLAlchemy models, repositories and Alembic migrations
  tools/               Strands @tool functions used by the assistant (one per file)
data/                  Local data: database, uploaded files, generated CVs (never commit this)
```

Rules for contributors: the frontend calls only the backend; all third-party calls live in `clients/`; routes
validate and delegate; business logic lives in `services/`; queries live in `db/`.

## Configuration

Settings are read from `job_agent/.env` (see `job_agent/.env.example`). Missing keys never stop the backend; the
affected source reports "not configured" and the rest keep working. `frontend/.env` holds the backend address and
the shared token.

## Security and privacy

- The backend listens on `127.0.0.1` only and requires an `X-API-Token` header on every route except the health check
  and API docs. Do not expose port 8001.
- `.env` files, `data/`, logs and credential files are excluded by `.gitignore`. Check `git status` before any commit.
- Gmail tokens are encrypted in the database with `ENCRYPTION_KEY`. Losing that key means reconnecting Gmail.
- Office repos are read only when you tick "Content allowed" for them.

## Testing

Most behaviour was checked with focused scripts on temporary databases (matching, deduplication, CV flow, thread
management and rendering). Before relying on a new feature, try it with a small search or a single draft.

## Known limits

- Coverage is partial for every source, and some postings will be missed.
- PredictLeads discovery may bill per returned result. Check the request log on the API usage page.
- Apollo emails can be wrong. Each contact shows its verification status.
- Cold emails from a personal Gmail can land in spam. Sending is one email at a time with a daily cap.
- Scores, CV proposals and drafts are suggestions. You decide.

## Licence

No licence has been chosen yet. Add one before publishing the repository for others to reuse.
