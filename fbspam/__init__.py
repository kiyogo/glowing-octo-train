"""fbspam — cookie-driven messenger fan-out."""
from .cookies import Account, load_accounts, extract_browsers
from .client import FBClient, Status
from .sender import Sender, Options, State

__version__ = "1.0.0"
__all__ = ["Account", "load_accounts", "extract_browsers", "FBClient", "Status",
           "Sender", "Options", "State"]
