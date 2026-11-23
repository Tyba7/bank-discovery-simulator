from itertools import combinations

import pytest

from app.content import load_content
from app.interview import client_system_prompt, product_note
from app.prompts import Prompt, variant_options


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


def test_product_note_carries_only_public_catalogue_text():
    content = load_content()
    note = product_note(list(content.products.values()))
    hidden = [x for c in content.clients.values() for n in c.hidden_needs for x in (n.id, n.fact, n.topic)]
    assert all(p.name in note for p in content.products.values())
    assert not [h for h in hidden if h in note]
    assert not [t for p in content.products.values() for t in p.tags if t in note]  # internal tags stay internal


def test_a_variant_overrides_only_its_own_files():
    default, variant = Prompt("client"), Prompt("client", "ki01")
    assert variant.text != default.text and variant.version != default.version
    assert Prompt("guard", "ki01").text == Prompt("guard").text  # no override: falls back to the default
    assert variant_options("ki01")["product_note"] is True and variant_options(None) == {}
    with pytest.raises(ValueError, match="Unknown prompt variant"):
        variant_options("no_such_variant")
