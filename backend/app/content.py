from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
SLUG = r"^[a-z][a-z0-9_]*$"


class ContentError(RuntimeError):
    pass


class Taxonomy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    need_categories: dict[str, str]
    product_categories: dict[str, str]
    client_tags: dict[str, str]
    need_tags: dict[str, str]
    product_tags: dict[str, str]


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    product_has: str | None = None
    product_lacks: str | None = None
    when_need: str | None = None  # a tag on one of the client's hidden needs
    unless_client: str | None = None  # a public client tag the client does not have
    verdict: Literal["suitable", "unsuitable", "investigate"]
    reason: str

    @model_validator(mode="after")
    def _one_condition_each(self):
        if (self.product_has is None) == (self.product_lacks is None):
            raise ValueError("set exactly one of product_has, product_lacks")
        if (self.when_need is None) == (self.unless_client is None):
            raise ValueError("set exactly one of when_need, unless_client")
        if self.verdict != "unsuitable" and self.when_need is None:
            raise ValueError("suitable and investigate rules need when_need")
        return self


class Product(BaseModel):
    id: str = Field(pattern=SLUG)
    name: str
    category: str
    tags: list[str] = Field(min_length=1)
    features: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)


class HiddenNeed(BaseModel):
    id: str = Field(pattern=SLUG)
    category: str
    tags: list[str] = []
    topic: str  # what a question must be about to reveal this need (classifier input)
    fact: str  # what the client may say once revealed


class Client(BaseModel):
    id: str = Field(pattern=SLUG)
    name: str
    age: int = Field(ge=18)
    occupation: str
    background: str  # public
    stated_goal: str  # public: why the client says they came in
    personality: str  # how the client talks
    tags: list[str] = []  # public attributes, e.g. business_owner
    hidden_needs: list[HiddenNeed] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_need_ids(self):
        ids = [n.id for n in self.hidden_needs]
        if len(ids) != len(set(ids)):
            raise ValueError("hidden need ids must be unique")
        return self


class Content(BaseModel):
    clients: dict[str, Client]
    products: dict[str, Product]
    taxonomy: Taxonomy
    rules: list[Rule]


def _parse(path: Path, adapter: TypeAdapter):
    try:
        return adapter.validate_json(path.read_text())
    except (OSError, ValidationError) as e:
        raise ContentError(f"{path.name}: {e}") from None


def load_content(directory: Path = CONTENT_DIR) -> Content:
    taxonomy = _parse(directory / "taxonomy.json", TypeAdapter(Taxonomy))
    rules = _parse(directory / "rules.json", TypeAdapter(list[Rule]))
    products = _parse(directory / "products.json", TypeAdapter(list[Product]))
    clients = [_parse(p, TypeAdapter(Client)) for p in sorted((directory / "clients").glob("*.json"))]

    errors = []
    if len(clients) < 2:
        errors.append("at least 2 clients are required")
    if len(products) < 3:
        errors.append("at least 3 products are required")
    for kind, ids in (
        ("client", [c.id for c in clients]),
        ("product", [p.id for p in products]),
        ("rule", [r.id for r in rules]),
    ):
        if dupes := {i for i in ids if ids.count(i) > 1}:
            errors.append(f"duplicate {kind} ids: {sorted(dupes)}")

    def check(owner: str, kind: str, values: list[str | None], vocabulary: dict[str, str]):
        if unknown := {v for v in values if v is not None} - vocabulary.keys():
            errors.append(f"{owner}: unknown {kind} {sorted(unknown)}")

    for p in products:
        check(f"product {p.id}", "category", [p.category], taxonomy.product_categories)
        check(f"product {p.id}", "product tags", p.tags, taxonomy.product_tags)
    for c in clients:
        check(f"client {c.id}", "client tags", c.tags, taxonomy.client_tags)
        for n in c.hidden_needs:
            check(f"client {c.id} need {n.id}", "category", [n.category], taxonomy.need_categories)
            check(f"client {c.id} need {n.id}", "need tags", n.tags, taxonomy.need_tags)
    for r in rules:
        check(f"rule {r.id}", "product tags", [r.product_has, r.product_lacks], taxonomy.product_tags)
        check(f"rule {r.id}", "need tags", [r.when_need], taxonomy.need_tags)
        check(f"rule {r.id}", "client tags", [r.unless_client], taxonomy.client_tags)
    if errors:
        raise ContentError("; ".join(errors))
    return Content(
        clients={c.id: c for c in clients},
        products={p.id: p for p in products},
        taxonomy=taxonomy,
        rules=rules,
    )
