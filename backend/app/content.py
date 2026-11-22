from pathlib import Path

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
SLUG = r"^[a-z][a-z0-9_]*$"


class ContentError(RuntimeError):
    pass


class Product(BaseModel):
    id: str = Field(pattern=SLUG)
    name: str
    category: str
    sharia_compliant: bool
    features: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)


class HiddenNeed(BaseModel):
    id: str = Field(pattern=SLUG)
    topic: str  # what a question must be about to reveal this need (classifier input)
    fact: str  # what the client may say once revealed
    suitable_products: list[str] = []


class UnsuitableProduct(BaseModel):
    product_id: str
    reason: str


class Client(BaseModel):
    id: str = Field(pattern=SLUG)
    name: str
    age: int = Field(ge=18)
    occupation: str
    background: str  # public
    stated_goal: str  # public: why the client says they came in
    personality: str  # how the client talks
    hidden_needs: list[HiddenNeed] = Field(min_length=1)
    unsuitable_products: list[UnsuitableProduct] = []

    @model_validator(mode="after")
    def _unique_need_ids(self):
        ids = [n.id for n in self.hidden_needs]
        if len(ids) != len(set(ids)):
            raise ValueError("hidden need ids must be unique")
        return self


class Content(BaseModel):
    clients: dict[str, Client]
    products: dict[str, Product]


def _parse(path: Path, adapter: TypeAdapter):
    try:
        return adapter.validate_json(path.read_text())
    except (OSError, ValidationError) as e:
        raise ContentError(f"{path.name}: {e}") from None


def load_content(directory: Path = CONTENT_DIR) -> Content:
    products = _parse(directory / "products.json", TypeAdapter(list[Product]))
    clients = [_parse(p, TypeAdapter(Client)) for p in sorted((directory / "clients").glob("*.json"))]

    errors = []
    if len(clients) < 2:
        errors.append("at least 2 clients are required")
    if len(products) < 3:
        errors.append("at least 3 products are required")
    for kind, ids in (("client", [c.id for c in clients]), ("product", [p.id for p in products])):
        if dupes := {i for i in ids if ids.count(i) > 1}:
            errors.append(f"duplicate {kind} ids: {sorted(dupes)}")
    product_ids = {p.id for p in products}
    for c in clients:
        refs = {pid for n in c.hidden_needs for pid in n.suitable_products}
        refs |= {u.product_id for u in c.unsuitable_products}
        if unknown := refs - product_ids:
            errors.append(f"client {c.id}: unknown product ids {sorted(unknown)}")
    if errors:
        raise ContentError("; ".join(errors))
    return Content(clients={c.id: c for c in clients}, products={p.id: p for p in products})
