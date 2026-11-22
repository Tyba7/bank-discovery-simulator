import shutil
from pathlib import Path

import pytest

from app.content import CONTENT_DIR, load_content
from app.suitability import assess, conflicts

HELDOUT_CLIENT = Path(__file__).resolve().parents[1] / "evals" / "heldout" / "layla_haddad.json"

# The answer key written by hand before the rules existed; the rules must reproduce it.
ANSWER_KEY = {
    "khalid_al_mansouri": {
        "murabaha_business_finance": "suitable",
        "islamic_savings_account": "suitable",
        "business_overdraft": "unsuitable",
        "equity_growth_fund": "unsuitable",
        "education_savings_plan": "unsuitable",
        "global_transfer_account": "neutral",
    },
    "maria_santos": {
        "education_savings_plan": "suitable",
        "global_transfer_account": "suitable",
        "equity_growth_fund": "unsuitable",
        "business_overdraft": "unsuitable",
        "murabaha_business_finance": "unsuitable",
        "islamic_savings_account": "neutral",
    },
    "layla_haddad": {
        "islamic_savings_account": "suitable",
        "equity_growth_fund": "unsuitable",
        "education_savings_plan": "unsuitable",
        "business_overdraft": "unsuitable",
        "murabaha_business_finance": "unsuitable",
        "global_transfer_account": "neutral",
    },
}


@pytest.fixture(scope="module")
def content(tmp_path_factory):
    # Shipped content plus the held-out eval client, so the rules are checked on a third profile.
    directory = shutil.copytree(CONTENT_DIR, tmp_path_factory.mktemp("content") / "content")
    shutil.copy(HELDOUT_CLIENT, directory / "clients")
    return load_content(directory)


@pytest.mark.parametrize("client_id", ANSWER_KEY)
def test_rules_reproduce_the_answer_key(content, client_id):
    client = content.clients[client_id]
    verdicts = {pid: assess(content, client, product).verdict for pid, product in content.products.items()}
    assert verdicts == ANSWER_KEY[client_id]


@pytest.mark.parametrize(
    ("client_id", "product_id", "needs"),
    [
        ("khalid_al_mansouri", "business_overdraft", {"sharia_compliance"}),
        ("khalid_al_mansouri", "murabaha_business_finance", set()),
        ("maria_santos", "equity_growth_fund", {"low_risk_tolerance"}),
        ("maria_santos", "business_overdraft", set()),
        ("layla_haddad", "equity_growth_fund", {"no_investment_experience", "wedding_savings"}),
    ],
)
def test_conflicts_name_the_needs_an_objection_reveals(content, client_id, product_id, needs):
    assert conflicts(content, content.clients[client_id], content.products[product_id]) == needs


@pytest.mark.parametrize(
    ("client_id", "product_id", "discovered", "outcome", "missed"),
    [
        ("khalid_al_mansouri", "business_overdraft", set(), "unsuitable", ["sharia_compliance"]),
        ("khalid_al_mansouri", "murabaha_business_finance", {"seasonal_cash_flow"}, "investigate", ["existing_lease"]),
        ("khalid_al_mansouri", "murabaha_business_finance", {"seasonal_cash_flow", "existing_lease"}, "suitable", []),
        ("maria_santos", "global_transfer_account", set(), "investigate", ["family_remittances"]),
        ("maria_santos", "global_transfer_account", {"family_remittances"}, "suitable", []),
        ("maria_santos", "islamic_savings_account", set(), "neutral", []),
    ],
)
def test_outcome_depends_on_what_the_student_uncovered(content, client_id, product_id, discovered, outcome, missed):
    result = assess(content, content.clients[client_id], content.products[product_id], discovered)
    assert (result.outcome, result.missed) == (outcome, missed)
