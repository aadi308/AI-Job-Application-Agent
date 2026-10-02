import pytest

from app.job_relevance import relevance_reasons


@pytest.mark.parametrize(
    ("title", "location"),
    [
        ("Machine Learning Engineer", "Remote - United States"),
        ("Senior MLOps Engineer", "Austin, TX"),
        ("Applied Scientist", "New York, New York"),
        ("AI Infrastructure Engineer", "San Francisco, California"),
        ("Research Engineer, Interpretability", "San Francisco, CA"),
        ("Applied AI, Research Engineer", "New York City, NY"),
        ("Research Engineer, Chip Design RL (Reinforcement Learning)", "Austin, TX"),
        ("Machine Learning Engineer", "Honolulu, HI"),
        ("ML Engineer", "Columbus, OH"),
    ],
)
def test_relevant_us_ai_roles(title, location):
    accepted, reasons = relevance_reasons({"title": title, "location": location})
    assert accepted is True
    assert reasons == ["ai_ml_title", "us_location"]


@pytest.mark.parametrize(
    ("title", "location", "reason"),
    [
        ("Machine Learning Engineer", "London, UK", "not_us_location"),
        ("Backend Engineer", "Remote - US", "not_ai_ml_role"),
        ("AI Sales Account Executive", "New York, NY", "excluded_title"),
        ("People Research Scientist, Recruiting", "San Francisco, CA", "excluded_title"),
        ("AI Infrastructure Operations, Demand Planning", "San Francisco, CA", "excluded_title"),
        ("Transformative AI Research Economist", "San Francisco, CA", "excluded_title"),
        ("ML Engineer", "", "location_missing"),
        ("ML Engineer", "London or Dublin", "not_us_location"),
    ],
)
def test_irrelevant_or_unverifiable_roles(title, location, reason):
    accepted, reasons = relevance_reasons({"title": title, "location": location})
    assert accepted is False
    assert reason in reasons
