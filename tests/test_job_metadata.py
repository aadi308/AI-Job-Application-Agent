from app.job_metadata import enrich_job


def test_enrich_job_extracts_explicit_remote_h1b_and_level_metadata():
    job = enrich_job(
        {
            "title": "Senior Machine Learning Engineer",
            "location": "Remote — United States",
            "description": (
                "This is a full-time remote role requiring 5+ years of experience. "
                "Visa sponsorship is available for qualified H-1B candidates."
            ),
        }
    )
    assert job["job_family"] == "ai_ml"
    assert job["employment_type"] == "full_time"
    assert job["work_mode"] == "remote"
    assert job["experience_level"] == "senior"
    assert job["sponsorship_status"] == "available"
    assert job["visa_categories"] == ["h1b"]


def test_enrich_job_does_not_guess_unstated_sponsorship_or_work_mode():
    job = enrich_job(
        {
            "title": "Product Manager",
            "location": "Chicago, IL",
            "description": "Lead a product roadmap and collaborate with engineering.",
        }
    )
    assert job["job_family"] == "product"
    assert job["work_mode"] == "unknown"
    assert job["sponsorship_status"] == "not_specified"
    assert job["visa_categories"] == []


def test_enrich_job_detects_sponsorship_restriction_and_opt_mentions():
    job = enrich_job(
        {
            "title": "Software Engineering Intern",
            "location": "On-site",
            "description": (
                "Internship for F-1 OPT or STEM OPT candidates. "
                "We are unable to provide visa sponsorship."
            ),
        }
    )
    assert job["employment_type"] == "internship"
    assert job["experience_level"] == "internship"
    assert job["work_mode"] == "onsite"
    assert job["sponsorship_status"] == "not_available"
    assert job["visa_categories"] == ["f1_opt", "stem_opt"]
