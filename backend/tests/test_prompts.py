from itertools import combinations

from app.content import load_content
from app.interview import client_system_prompt
from app.prompts import Prompt


def test_client_prompt_never_contains_locked_information():
    content, prompt = load_content(), Prompt("client")
    rule_reasons = [r.reason for r in content.rules]
    for client in content.clients.values():
        ids = [n.id for n in client.hidden_needs]
        for size in range(len(ids) + 1):
            for unlocked in map(set, combinations(ids, size)):
                text = client_system_prompt(prompt, client, unlocked)
                for need in client.hidden_needs:
                    if need.id not in unlocked:
                        assert need.fact not in text and need.topic not in text and need.id not in text
                assert not any(reason in text for reason in rule_reasons)
