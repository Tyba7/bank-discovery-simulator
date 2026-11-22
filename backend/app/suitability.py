from dataclasses import dataclass
from typing import Literal

from app.content import Client, Content, Product, Rule


@dataclass(frozen=True)
class Match:
    rule: Rule
    need_id: str | None  # the hidden need that triggered the rule; None for client-tag rules


@dataclass(frozen=True)
class Assessment:
    product_id: str
    verdict: Literal["suitable", "unsuitable", "neutral"]  # ground truth, using every hidden need
    outcome: Literal["suitable", "unsuitable", "neutral", "investigate"]  # judged on the needs the student uncovered
    matches: list[Match]
    missed: list[str]  # hidden needs behind this product's verdict that the student did not uncover


def matches(rules: list[Rule], client: Client, product: Product) -> list[Match]:
    found = []
    for rule in rules:
        if rule.product_has and rule.product_has not in product.tags:
            continue
        if rule.product_lacks and rule.product_lacks in product.tags:
            continue
        if rule.unless_client:
            if rule.unless_client not in client.tags:
                found.append(Match(rule, None))
        else:
            found += [Match(rule, n.id) for n in client.hidden_needs if rule.when_need in n.tags]
    return found


def assess(content: Content, client: Client, product: Product, discovered: set[str] | None = None) -> Assessment:
    if discovered is None:  # ground truth: the adviser knows every need
        discovered = {n.id for n in client.hidden_needs}
    found = matches(content.rules, client, product)
    unsuitable = [m for m in found if m.rule.verdict == "unsuitable"]
    suitable = [m for m in found if m.rule.verdict == "suitable"]
    checks = [m for m in found if m.rule.verdict == "investigate"]
    verdict = "unsuitable" if unsuitable else "suitable" if suitable else "neutral"

    if unsuitable:
        missed = {m.need_id for m in unsuitable if m.need_id and m.need_id not in discovered}
    else:
        missed = {m.need_id for m in checks if m.need_id not in discovered}
        if suitable and not any(m.need_id in discovered for m in suitable):
            missed |= {m.need_id for m in suitable}  # right product, but the student never found out why
    outcome = "unsuitable" if unsuitable else "investigate" if missed else verdict
    return Assessment(product.id, verdict, outcome, found, sorted(missed))


def conflicts(content: Content, client: Client, product: Product) -> set[str]:
    # Hidden needs the client reveals by objecting when this product is proposed (eval rule 1).
    return {m.need_id for m in matches(content.rules, client, product) if m.rule.verdict == "unsuitable" and m.need_id}
