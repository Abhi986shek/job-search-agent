"""Strands @tool functions, one per file, named for what they do.

The agent gets no tool to upload files, select repos, confirm roles, approve CV changes, generate CV files,
reveal Apollo emails, connect Gmail, or send email. Those are UI buttons, so they always need the user's click.
"""

from tools.add_job_url_for_guidance import add_job_url_for_guidance
from tools.build_my_profile import build_my_profile
from tools.check_email_replies import check_email_replies
from tools.draft_outreach_message import draft_outreach_message
from tools.draft_reply_to_message import draft_reply_to_message
from tools.find_job_contacts import find_job_contacts
from tools.get_api_usage import get_api_usage
from tools.get_job_details import get_job_details
from tools.get_my_profile import get_my_profile
from tools.get_profile_inputs import get_profile_inputs
from tools.list_github_repos import list_github_repos
from tools.list_job_matches import list_job_matches
from tools.read_linkedin_posts import read_linkedin_posts
from tools.list_outreach_threads import list_outreach_threads
from tools.list_saved_jobs import list_saved_jobs
from tools.list_target_roles import list_target_roles
from tools.match_jobs_to_profile import match_jobs_to_profile
from tools.propose_cv_changes import propose_cv_changes
from tools.read_github_file import read_github_file
from tools.read_github_repo import read_github_repo
from tools.propose_target_roles import propose_target_roles
from tools.save_target_role import save_target_role
from tools.search_company_jobs import search_company_jobs
from tools.search_jobs import search_jobs
from tools.suggest_onet_codes import suggest_onet_codes
from tools.update_job_status import update_job_status

ALL_TOOLS = [
    # Stage 1-2: inputs and profile
    get_profile_inputs,
    build_my_profile,
    get_my_profile,
    # Stage 3: target roles
    list_target_roles,
    propose_target_roles,
    save_target_role,
    suggest_onet_codes,
    # Stage 4: jobs
    search_jobs,
    search_company_jobs,
    add_job_url_for_guidance,
    list_saved_jobs,
    get_job_details,
    update_job_status,
    # Stage 5-6: matching and CV
    match_jobs_to_profile,
    list_job_matches,
    propose_cv_changes,
    # Stage 7-8: outreach and replies
    find_job_contacts,
    draft_outreach_message,
    check_email_replies,
    draft_reply_to_message,
    list_outreach_threads,
    # Reading the owner's repos (read-only; office repos only when content is allowed)
    list_github_repos,
    read_github_repo,
    read_github_file,
    # Reading the owner's LinkedIn posts from the stored export (no live fetch)
    read_linkedin_posts,
    # Any time
    get_api_usage,
]
