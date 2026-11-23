import json
import shutil

import pytest

from app.content import CONTENT_DIR, ContentError, load_content


def test_shipped_content_is_valid():
    content = load_content()
    assert len(content.clients) >= 2 and len(content.products) >= 3 and content.rules


@pytest.fixture
def content_copy(tmp_path):
    return shutil.copytree(CONTENT_DIR, tmp_path / "content")


def edit(path, change):
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def test_invalid_file_error_names_the_file(content_copy):
    (content_copy / "products.json").write_text("[{}]")
    with pytest.raises(ContentError, match="products.json"):
        load_content(content_copy)


def test_unknown_product_tag_is_rejected(content_copy):
    edit(content_copy / "products.json", lambda d: d[0]["tags"].append("interest_bearng"))
    with pytest.raises(ContentError, match="interest_bearng"):
        load_content(content_copy)


def test_unknown_need_category_is_rejected(content_copy):
    edit(content_copy / "clients" / "maria_santos.json", lambda d: d["hidden_needs"][0].update(category="hobbies"))
    with pytest.raises(ContentError, match="hobbies"):
        load_content(content_copy)


def test_rule_with_unknown_need_tag_is_rejected(content_copy):
    edit(content_copy / "rules.json", lambda d: d[0].update(when_need="likes_cats"))
    with pytest.raises(ContentError, match="likes_cats"):
        load_content(content_copy)


def test_rule_needs_exactly_one_product_condition(content_copy):
    edit(content_copy / "rules.json", lambda d: d[0].update(product_has="interest_bearing"))  # R01 has product_lacks
    with pytest.raises(ContentError, match="exactly one of product_has, product_lacks"):
        load_content(content_copy)


def test_public_text_states_sharia_compliance_exactly_when_tagged():
    # The rules read tags; students and the client read features. They must agree, or a compliant product looks
    # interest-bearing to the client (KI-01: Khalid rejected Murabaha as "interest-based").
    for p in load_content().products.values():
        says = any("sharia-compliant" in f.lower() for f in p.features)
        assert says == ("sharia_compliant" in p.tags), p.id
