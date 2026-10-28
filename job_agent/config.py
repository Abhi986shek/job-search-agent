"""Settings for the job agent backend.

All configuration comes from job_agent/.env. Code reads `settings`, never os.getenv.
Empty values mean "not configured"; a source without keys reports that instead of failing.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent          # job_agent/
PROJECT_DIR = BASE_DIR.parent                       # job-search-agent/
DATA_DIR = PROJECT_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Backend
    APP_ENV: str = "local"
    LOG_FILE: str = "app.log"
    HOST: str = "127.0.0.1"
    PORT: int = 8001

    BACKEND_API_TOKEN: str = ""
    HTTP_TIMEOUT_SECONDS: float = 30.0

    # Database and secrets
    DATABASE_URL: str = ""
    ENCRYPTION_KEY: str = ""

    # Job sources
    PREDICTLEADS_API_KEY: str = ""
    PREDICTLEADS_API_TOKEN: str = ""
    # Discover endpoints may bill per returned result, so keep this small
    PREDICTLEADS_DISCOVER_LIMIT: int = 25
    SERPAPI_API_KEY: str = ""
    SERPAPI_MAX_PAGES: int = 1
    ADZUNA_APP_ID: str = ""
    ADZUNA_APP_KEY: str = ""
    ADZUNA_COUNTRY: str = "in"
    # freehire public API (keyless).
    FREEHIRE_COUNTRY: str = "IN"
    FREEHIRE_EXCLUDE_SOURCES: str = ""
    # Pages of 100 read per search, until enough jobs pass the filters. One request per page.
    FREEHIRE_MAX_PAGES: int = 3

    # GitHub 
    GITHUB_PERSONAL_TOKEN: str = ""
    GITHUB_PERSONAL_USERNAME: str = ""
    GITHUB_COMPANY_TOKEN: str = ""
    GITHUB_COMPANY_ORG: str = ""

    # LinkedIn own profile
    APIFY_TOKEN: str = ""
    APIFY_LINKEDIN_ACTOR: str = "harvestapi/linkedin-profile-scraper"
    LINKEDIN_PROFILE_URL: str = ""

    # Contact finder 
    APOLLO_API_KEY: str = ""

    # Personal Gmail 
    GMAIL_ADDRESS: str = ""
    GMAIL_OAUTH_CLIENT_FILE: str = ""
    EMAIL_DAILY_SEND_CAP: int = 20
    REPLY_CHECK_MINUTES: int = 15
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    IMAP_HOST: str = "imap.gmail.com"
    SMTP_USERNAME: str = ""
    SMTP_APP_PASSWORD: str = ""

    # AWS Bedrock
    AWS_REGION: str = ""
    AWS_PROFILE: str = ""
    BEDROCK_MODEL_ID: str = ""

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"sqlite:///{(DATA_DIR / 'job_agent.db').as_posix()}"

    @property
    def log_path(self) -> Path:
        p = Path(self.LOG_FILE)
        return p if p.is_absolute() else BASE_DIR / p

    # Configured flags 
    @property
    def predictleads_configured(self) -> bool:
        return bool(self.PREDICTLEADS_API_KEY and self.PREDICTLEADS_API_TOKEN)

    @property
    def serpapi_configured(self) -> bool:
        return bool(self.SERPAPI_API_KEY)

    @property
    def adzuna_configured(self) -> bool:
        return bool(self.ADZUNA_APP_ID and self.ADZUNA_APP_KEY)

    @property
    def bedrock_configured(self) -> bool:
        return bool(self.BEDROCK_MODEL_ID and self.AWS_REGION)


settings = Settings()

for _d in (DATA_DIR, UPLOADS_DIR, OUTPUTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
