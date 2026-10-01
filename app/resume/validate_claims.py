import re

from app.candidate.models import CandidateProfile
from app.resume.models import ClaimValidationReport, StructuredResume

NUMBER_PATTERN = re.compile(r"\d[\d,.]*%?\+?")
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "with", "for", "to", "of", "in", "on", "at",
    "by", "from", "as", "is", "was", "were", "be", "been", "being", "that", "this",
    "these", "those", "it", "its", "into", "used", "via",
}
MIN_BULLET_WORD_OVERLAP = 0.3


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _numbers_in(text: str) -> set[str]:
    # Strip a trailing "+" so paraphrasing "99%+" as "above/over 99%" isn't flagged as an
    # invented number — only the core figure has to match, not the "or more" modifier.
    return {n.rstrip("+") for n in NUMBER_PATTERN.findall(text)}


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def validate_claims(resume: StructuredResume, profile: CandidateProfile) -> ClaimValidationReport:
    """Deterministic, non-LLM checks. The tailoring LLM never grades its own work here."""
    violations: list[str] = []

    # Completeness, not just truthfulness: a resume with zero experience entries has
    # nothing false to flag in the checks below, but it's still useless — discovered for
    # real when tailoring against a badly-mismatched job caused the model to return an
    # empty selection entirely rather than honestly-tailored real content.
    if profile.employment and not resume.experience:
        violations.append(
            "Tailored resume has zero experience entries despite the candidate having "
            f"{len(profile.employment)} real employment entries in their profile — the "
            "tailoring step produced an empty/degenerate selection."
        )
    # Same completeness gap, different field — discovered for real: Groq returned
    # skill_indices as one malformed concatenated string ("013712131416...") instead of
    # a proper JSON array of ints. The index-coercion in tailor.py correctly rejects that
    # rather than guessing how to split it, but the net effect (silently empty skills on
    # a resume for a candidate with 59 real listed skills) is exactly as unusable as the
    # empty-experience case and deserves the same visibility.
    if profile.skills and not resume.skills:
        violations.append(
            "Tailored resume has zero skills despite the candidate having "
            f"{len(profile.skills)} real skills in their profile — the tailoring step's "
            "skill selection failed (e.g. malformed indices from the model)."
        )
    # Projects are curated (not "always all", unlike education) since relevance genuinely
    # varies by job — but a candidate with real projects should never end up with zero
    # unless none were relevant, which the tailoring prompt actively discourages. Mirrors
    # the skills/experience empty-selection check above.
    if profile.projects and not resume.projects:
        violations.append(
            "Tailored resume has zero projects despite the candidate having "
            f"{len(profile.projects)} real projects in their profile — likely an empty/"
            "degenerate selection rather than a genuine relevance judgment."
        )

    # Education is no longer LLM-selected at all (tailor.py always includes every real
    # entry — see comment there), so this should be unreachable in practice. Kept anyway
    # as a regression guard: this exact bug (a real, currently-in-progress M.S. entry
    # silently dropped from every generated resume) was found by inspecting real output,
    # not by any existing check, which is exactly the gap this closes.
    if len(resume.education) < len(profile.education):
        missing = len(profile.education) - len(resume.education)
        violations.append(
            f"Tailored resume is missing {missing} of {len(profile.education)} real "
            "education entries from the candidate's profile."
        )

    c = profile.contact
    if c.email.value and resume.header.email != c.email.value:
        violations.append(
            f"Email mismatch: resume has {resume.header.email!r}, profile has {c.email.value!r}"
        )
    if c.phone.value and resume.header.phone != c.phone.value:
        violations.append(
            f"Phone mismatch: resume has {resume.header.phone!r}, profile has {c.phone.value!r}"
        )

    # Keyed by (company, title) — not company alone — since a candidate can hold multiple
    # roles at the same employer (e.g. an internship followed by a full-time role).
    profile_jobs_by_key = {(job.company, job.title): job for job in profile.employment}
    for entry in resume.experience:
        real_job = profile_jobs_by_key.get((entry.company, entry.title))
        if real_job is None:
            same_company = [j for j in profile.employment if j.company == entry.company]
            if same_company:
                violations.append(
                    f"Title not found for {entry.company}: resume has {entry.title!r}, "
                    f"profile has {[j.title for j in same_company]}"
                )
            else:
                violations.append(f"Employer not found in profile: {entry.company!r}")
            continue
        if entry.dates != real_job.dates:
            violations.append(
                f"Dates mismatch for {entry.company}: resume has {entry.dates!r}, "
                f"profile has {real_job.dates!r}"
            )

        real_bullets_normalized = [_normalize(b) for b in real_job.bullets]
        for bullet in entry.bullets:
            source_normalized = _normalize(bullet.source_bullet)
            if not any(
                source_normalized == rb or source_normalized in rb or rb in source_normalized
                for rb in real_bullets_normalized
            ):
                violations.append(
                    f"Unverifiable source_bullet for {entry.company}: "
                    f"{bullet.source_bullet!r} does not match any real bullet in the profile"
                )
                continue

            invented_numbers = _numbers_in(bullet.text) - _numbers_in(bullet.source_bullet)
            if invented_numbers:
                violations.append(
                    f"Possible invented metric in bullet for {entry.company}: "
                    f"{invented_numbers} not present in source bullet {bullet.source_bullet!r}"
                )

            # Discovered for real: tailor.py builds source_bullet from a real profile
            # bullet by index, so the check above always passes even when the model
            # returns completely unrelated fabricated text under an accurate-looking
            # citation — e.g. a "Designed user-centered experiences..." bullet_text
            # tagged with a real bullet_index pointing at an actual Terraform/AWS bullet.
            # That case has no invented numbers to catch (there are no numbers in it at
            # all), so it needs a separate check: the rephrase has to actually share
            # vocabulary with what it claims to be rephrasing.
            text_words = _significant_words(bullet.text)
            source_words = _significant_words(bullet.source_bullet)
            if text_words and source_words:
                overlap = len(text_words & source_words) / len(text_words)
                if overlap < MIN_BULLET_WORD_OVERLAP:
                    violations.append(
                        f"Bullet for {entry.company} shares little vocabulary with its "
                        f"cited source bullet ({overlap:.0%} overlap) — likely unrelated "
                        f"or fabricated content rather than a rephrase: {bullet.text!r} "
                        f"(cited source: {bullet.source_bullet!r})"
                    )

    real_project_names = [_normalize(p.name) for p in profile.projects]
    for entry in resume.projects:
        if _normalize(entry.name) not in real_project_names:
            violations.append(f"Project not found in profile: {entry.name!r}")

    real_education = [(e.institution, e.degree, e.dates) for e in profile.education]
    for entry in resume.education:
        if (entry.institution, entry.degree, entry.dates) not in real_education:
            violations.append(
                f"Education entry not found in profile: {entry.degree} at "
                f"{entry.institution} ({entry.dates})"
            )

    # Containment on punctuation-stripped text, not exact match: the profile's skill list
    # and the tailored resume's skill list come from two separate LLM calls that may
    # phrase the same real skill differently in punctuation/spacing (e.g. profile has
    # "Kubernetes (EKS / AKS / GKE)", tailored resume says "Kubernetes (EKS/AKS/GKE)") —
    # only flag a skill that isn't a substring of, or doesn't contain, anything real.
    def _skill_key(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    real_skills = [_skill_key(s.skill) for s in profile.skills]
    for skill in resume.skills:
        key = _skill_key(skill)
        if not any(key in rs or rs in key for rs in real_skills):
            violations.append(f"Skill not found in profile: {skill!r}")

    return ClaimValidationReport(passed=len(violations) == 0, violations=violations)
