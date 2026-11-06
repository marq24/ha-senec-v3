import logging

_LOGGER = logging.getLogger(__name__)


class ServiceUnavailableException(Exception):
    """Raised when the backend service or device cannot be reached."""


class ReConfigurationRequired(Exception):
    """The provided TOTP Secret could not be validated"""
