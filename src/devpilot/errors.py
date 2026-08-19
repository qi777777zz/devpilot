class RuntimeErrorBase(RuntimeError):
    """Base class for failures that carry runtime semantics."""


class InvalidTaskStateError(RuntimeErrorBase):
    pass


class BudgetExceededError(RuntimeErrorBase):
    pass


class RetryableStepError(RuntimeErrorBase):
    """A transient node failure that may succeed when executed again."""


class LeaseLostError(RuntimeErrorBase):
    """The worker no longer owns the job it attempted to update."""
