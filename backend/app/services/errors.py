"""Domain errors that map onto RFC 7807 problem+json responses."""


class AppError(Exception):
    """Base class for errors with a client-safe representation."""

    status: int = 500
    problem_type: str = "/errors/internal"
    title: str = "Internal server error"

    def __init__(
        self,
        detail: str,
        *,
        problem_type: str | None = None,
        title: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if problem_type is not None:
            self.problem_type = problem_type
        if title is not None:
            self.title = title
        if status is not None:
            self.status = status


class UnsupportedDocumentError(AppError):
    status = 422
    problem_type = "/errors/unsupported-document"
    title = "Unsupported document"


class DocumentTooLargeError(AppError):
    status = 413
    problem_type = "/errors/document-too-large"
    title = "Document too large"


class NotFoundError(AppError):
    status = 404
    problem_type = "/errors/not-found"
    title = "Not found"


class DocumentNotReadyError(AppError):
    status = 409
    problem_type = "/errors/document-not-ready"
    title = "Document not ready"


class NoDocumentsError(AppError):
    status = 409
    problem_type = "/errors/no-documents"
    title = "No documents to search"


class ProviderError(AppError):
    status = 502
    problem_type = "/errors/ai-provider"
    title = "AI provider error"
