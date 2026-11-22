import json
import shutil

import pytest

from app.content import CONTENT_DIR, ContentError, load_content


def test_shipped_content_is_valid():
    content = load_content()
    assert len(content.clients) >= 2 and len(content.products) >= 3


@pytest.fixture
def content_copy(tmp_path):
    return shutil.copytree(CONTENT_DIR, tmp_path / "content")


def test_unknown_product_id_is_rejected(content_copy):
    path = content_copy / "clients" / "maria_santos.json"
    data = json.loads(path.read_text())
    data["unsuitable_products"][0]["product_id"] = "no_such_product"
    path.write_text(json.dumps(data))
    with pytest.raises(ContentError, match="no_such_product"):
        load_content(content_copy)


def test_invalid_file_error_names_the_file(content_copy):
    (content_copy / "products.json").write_text("[{}]")
    with pytest.raises(ContentError, match="products.json"):
        load_content(content_copy)
