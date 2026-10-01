from datetime import datetime, timezone

from app.agents.state import JobApplicationState
from app.llm.audit import record_evaluation
from app.llm.config import get_router
from app.llm.exceptions import AllProvidersFailedError

AGENT_NAME = "networking"
PROMPT_VERSION = "v2-groq"

SYSTEM_PROMPT = """You draft short, professional LinkedIn outreach messages for a real job \
candidate reaching out about a specific role. You do not send anything to anyone — you only \
draft text for the candidate to review, edit, and send themselves.

STRICT RULES:
- Base the message only on real facts from the candidate's resume context and the job posting \
provided below. Do not fabricate shared connections, mutual contacts, referrals, or claims not \
present in the source material.
- Keep it concise (under 100 words), specific to this company/role/track (not generic \
boilerplate), professional in tone, and end with a clear, low-pressure ask (e.g. a brief chat, \
or simply expressing genuine interest in the role).
- No recipient name is available. Do not address the message to any name and do not use a \
bracketed placeholder for one (no "[Name]", "[Recipient's Name]", "[Hiring Manager]", etc.) — \
either open with something like "Hi," on its own, or skip a named greeting entirely and start \
straight into the message.
- Output only the message text — no subject line, no commentary, no other placeholders.
"""


def networking_node(state: JobApplicationState) -> dict:
    router = get_router()
    started_at = datetime.now(timezone.utc)
    user_prompt = f"""Candidate resume context (for tone/background only — do not invent facts \
beyond this):
{state['resume_context']}

Target job:
Company: {state['company']}
Title: {state['title']}
Track: {state['track']}
Job posting excerpt: {(state.get('description') or '')[:800]}

Draft the outreach message now.
"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        routed = router.generate(
            messages=messages,
            complexity="routine",  # short outreach draft — explicitly a routine-tier task
            # Same class of bug already found in extraction: gpt-oss models spend part of
            # this budget on hidden reasoning before visible output. Reproduced for real
            # here — 700 wasn't enough headroom and produced a message truncated after 4
            # words ("Hi, I'm Jordan Lee"). The desired output is small (<100 words,
            # ~150 tokens) but the budget has to cover unpredictable reasoning overhead on
            # top of that, not just the visible text.
            max_completion_tokens=1500,
            temperature=0.3,
        )
    except AllProvidersFailedError as e:
        record_evaluation(
            agent_name=AGENT_NAME, evaluation_status="EVALUATION_FAILED", started_at=started_at,
            job_id=state.get("job_id"), safe_error_message=str(e)[:300],
            prompt_version=PROMPT_VERSION,
        )
        raise

    record_evaluation(
        agent_name=AGENT_NAME, evaluation_status="COMPLETED", started_at=started_at,
        job_id=state.get("job_id"), routed=routed, prompt_version=PROMPT_VERSION,
    )
    return {"outreach_message": routed.result.content}
