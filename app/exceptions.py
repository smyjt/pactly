class PactlyError(Exception):
    """Base exception for all Pactly errors."""
    pass


class ContractNotFoundError(PactlyError):
    def __init__(self, contract_id: str):
        self.contract_id = contract_id
        super().__init__(f"Contract {contract_id} not found")


class DuplicateContractError(PactlyError):
    def __init__(self, file_hash: str):
        self.file_hash = file_hash
        super().__init__(f"Contract with this file already exists")


class UnsupportedFileTypeError(PactlyError):
    def __init__(self, content_type: str):
        self.content_type = content_type
        super().__init__(f"Unsupported file type: {content_type}. Only PDF and DOCX are accepted.")


class LLMProviderError(PactlyError):
    """Raised when an LLM API call fails after all retries."""
    pass
