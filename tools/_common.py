"""Shared adapter: every tools/*.py handler wraps its domain call with this.
This is the 'ambiguity contract' from the plan -- a tool never decides *what*
to say or silently guesses; it reports what it found (a single match /
several candidates / nothing / a refusal) as a structured status, and the
model decides what to do next. A DomainError never reaches the model as a
raw traceback."""

from domain.errors import (
    AmbiguousMatchError,
    BelowCostError,
    DomainError,
    NotFoundError,
    OversellError,
    ValidationError,
)


def call_domain(fn) -> dict:
    try:
        result = fn()
    except AmbiguousMatchError as e:
        return {"status": "needs_clarification", "candidates": e.candidates}
    except NotFoundError as e:
        return {"status": "not_found", "message": str(e)}
    except OversellError as e:
        return {"status": "insufficient_stock", "shortfalls": e.shortfalls}
    except BelowCostError as e:
        return {"status": "below_cost", "items": e.items}
    except ValidationError as e:
        return {"status": "rejected", "message": str(e)}
    except DomainError as e:
        return {"status": "error", "message": str(e)}

    if isinstance(result, dict):
        return {"status": "ok", **result}
    if isinstance(result, list):
        return {"status": "ok", "items": result}
    return {"status": "ok", "result": result}
