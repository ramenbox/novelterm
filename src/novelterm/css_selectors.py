"""A small CSS selector subset for source files.

Supported:
    tag             div
    class           .episode-content   div.episode-content.wide
    id              #main              main#main
    descendant      div.title h1
    child           ul.chapters > li > a
"""

import re
from dataclasses import dataclass
from enum import Enum, auto

from novelterm.html_tree import Element

COMPOUND_PATTERN = re.compile(r"^(?P<tag>[a-zA-Z][a-zA-Z0-9-]*|\*)?(?P<rest>(?:[.#][a-zA-Z0-9_-]+)*)$")


class SelectorError(ValueError):
    pass


class Combinator(Enum):
    DESCENDANT = auto()
    CHILD = auto()


@dataclass(frozen=True)
class CompoundSelector:
    tag: str | None
    classes: tuple[str, ...]
    element_id: str | None

    def matches(self, element: Element) -> bool:
        return (
            (self.tag is None or element.tag == self.tag)
            and all(class_name in element.classes() for class_name in self.classes)
            and (self.element_id is None or element.get("id") == self.element_id)
        )


@dataclass(frozen=True)
class SelectorStep:
    combinator: Combinator
    compound: CompoundSelector


@dataclass(frozen=True)
class Selector:
    text: str
    steps: tuple[SelectorStep, ...]

    def select(self, root: Element) -> list[Element]:
        """All matching elements, in document order."""
        current = [root]
        for step in self.steps:
            found: dict[int, Element] = {}
            for element in current:
                match step.combinator:
                    case Combinator.DESCENDANT:
                        candidates = element.descendants()
                    case Combinator.CHILD:
                        candidates = (child for child in element.children if isinstance(child, Element))
                for candidate in candidates:
                    if step.compound.matches(candidate):
                        found[id(candidate)] = candidate
            current = list(found.values())
        document_order = {id(element): index for index, element in enumerate(root.descendants())}
        return sorted(current, key=lambda element: document_order.get(id(element), -1))

    def select_first(self, root: Element) -> Element | None:
        return next(iter(self.select(root)), None)


def parse_compound(text: str) -> CompoundSelector:
    match_result = COMPOUND_PATTERN.match(text)
    if match_result is None or not text:
        raise SelectorError(f"cannot read selector part '{text}'")
    tag = match_result.group("tag")
    parts = re.findall(r"[.#][a-zA-Z0-9_-]+", match_result.group("rest"))
    element_ids = [part[1:] for part in parts if part.startswith("#")]
    if len(element_ids) > 1:
        raise SelectorError(f"selector part '{text}' has more than one #id")
    return CompoundSelector(
        tag=None if tag in (None, "*") else tag.lower(),
        classes=tuple(part[1:] for part in parts if part.startswith(".")),
        element_id=element_ids[0] if element_ids else None,
    )


def parse_selector(text: str) -> Selector:
    tokens = text.replace(">", " > ").split()
    if not tokens:
        raise SelectorError("selector is empty")
    steps: list[SelectorStep] = []
    combinator = Combinator.DESCENDANT
    for token in tokens:
        match token:
            case ">" if steps and combinator == Combinator.DESCENDANT:
                combinator = Combinator.CHILD
            case ">":
                raise SelectorError(f"misplaced '>' in '{text}'")
            case _:
                steps.append(SelectorStep(combinator, parse_compound(token)))
                combinator = Combinator.DESCENDANT
    if combinator == Combinator.CHILD:
        raise SelectorError(f"'{text}' ends with '>'")
    return Selector(text=text, steps=tuple(steps))
