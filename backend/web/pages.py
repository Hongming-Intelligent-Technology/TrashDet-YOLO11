from .blueprint import web_bp

# Import side effects: register hooks and routes on `web_bp`.
from . import routes_auth as _routes_auth  # noqa: F401
from . import routes_admin as _routes_admin  # noqa: F401
from . import routes_context as _routes_context  # noqa: F401
from . import routes_data as _routes_data  # noqa: F401
from . import routes_spa as _routes_spa  # noqa: F401

__all__ = ['web_bp']
