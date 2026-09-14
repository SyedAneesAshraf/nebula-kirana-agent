"""Domain-level exceptions. The MCP tool adapters (tools/*.py, added in Phase 2)
catch these and translate them into structured tool results the model can reason
over -- these are never meant to surface as raw Python tracebacks to the model."""


class DomainError(Exception):
    """Base class for business-rule violations."""


class NotFoundError(DomainError):
    """A referenced product/customer/bill/line does not exist."""


class AmbiguousMatchError(DomainError):
    """A free-text lookup matched more than one plausible record."""

    def __init__(self, candidates: list[dict]):
        self.candidates = candidates
        super().__init__(f"{len(candidates)} possible matches")


class ValidationError(DomainError):
    """Input failed a business-rule check (bad qty, unknown GST slab, etc.)."""


class OversellError(DomainError):
    """One or more bill lines exceed available stock at finalize time."""

    def __init__(self, shortfalls: list[dict]):
        self.shortfalls = shortfalls
        super().__init__("insufficient stock for one or more lines")


class BelowCostError(DomainError):
    """One or more bill lines are priced below the product's cost price."""

    def __init__(self, items: list[dict]):
        self.items = items
        super().__init__("one or more lines priced below cost")
