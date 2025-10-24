class EFRISIntegrationError(Exception):
    """Base exception for EFRIS integration errors"""
    pass


class EFRISConfigurationError(EFRISIntegrationError):
    """Configuration related errors"""
    pass


class EFRISAPIError(EFRISIntegrationError):
    """API communication errors"""
    def __init__(self, message: str, error_code: str = None, response_data: dict = None):
        super().__init__(message)
        self.error_code = error_code
        self.response_data = response_data or {}


class EFRISValidationError(EFRISIntegrationError):
    """Data validation errors"""
    pass


class EFRISAuthenticationError(EFRISIntegrationError):
    """Authentication related errors"""
    pass


class EFRISBusinessLogicError(EFRISIntegrationError):
    """Business logic validation errors"""
    pass
