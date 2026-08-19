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


class PatchPolicyError(RuntimeErrorBase):
    """A proposed patch violates a deterministic repository safety rule."""


class PatchApplyError(RuntimeErrorBase):
    """A policy-approved patch cannot be applied to the staged workspace."""


class ModelProviderError(RuntimeErrorBase):
    """A model request or structured response failed deterministically."""
