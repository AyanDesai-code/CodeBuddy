from abc import ABC, abstractmethod


class IntegrationError(Exception):
    pass


class BaseIntegration(ABC):
    provider = None
    base_url = None

    def __init__(self, account):
        self.account = account

    @abstractmethod
    def get_access_token(self):
        """
        Return a valid access token.

        Providers can refresh an expired token here.
        """
        raise NotImplementedError

    @abstractmethod
    def request(
        self,
        method,
        path,
        *,
        params=None,
        json=None,
    ):
        """
        Perform an authenticated provider API request.
        """
        raise NotImplementedError