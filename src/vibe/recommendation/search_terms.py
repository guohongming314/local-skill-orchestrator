"""Provider-neutral discovery query expansion."""

from dataclasses import dataclass

_CAPABILITY_TERMS = {
    "code.optimization": ("code optimization", "refactoring", "static analysis"),
    "development.design": (
        "development design",
        "implementation planning",
        "architecture workflow",
    ),
    "repository.exploration": ("repository exploration", "code search", "symbol index"),
    "quality.gates": ("quality gates", "lint typecheck test security scan"),
    "project.continuity-memory": ("cross session project memory", "decision memory"),
    "browser.validation": (
        "browser automation",
        "browser testing",
        "interactive browser debugging",
    ),
}


@dataclass(frozen=True)
class DiscoveryQueryContext:
    capability: str
    languages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    user_product_leads: tuple[str, ...] = ()


def discovery_queries(context: DiscoveryQueryContext) -> tuple[str, ...]:
    terms = _CAPABILITY_TERMS.get(context.capability, (context.capability,))
    queries = [context.capability]
    languages = " ".join(context.languages).strip()
    if languages:
        queries.append(f"{languages} {' '.join(terms)}")
    frameworks = " ".join(context.frameworks).strip()
    if frameworks:
        queries.append(f"{frameworks} {' '.join(terms)}")
    queries.extend(f"{lead} {terms[0]}" for lead in context.user_product_leads if lead)
    return tuple(dict.fromkeys(queries))
