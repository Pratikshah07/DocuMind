"""Anonymous demo workspaces.

The browser generates a random token once and sends it as ``X-Workspace-Token``.
The server stores only its SHA-256, and every document query is filtered by it,
so a visitor can only see what that browser uploaded. This is isolation for a
public demo, NOT authentication: whoever holds the token has the workspace.
"""

import hashlib
import re

from app.core.errors import UnauthorizedError, ValidationFailedError

WORKSPACE_HEADER = "X-Workspace-Token"
LOCAL_WORKSPACE = "local"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def workspace_id_from_token(token: str | None, *, required: bool) -> str:
    if not token:
        if required:
            raise UnauthorizedError(
                "A workspace token is required. Reload the page to create one.", code="workspace_required"
            )
        return LOCAL_WORKSPACE
    if not _TOKEN_RE.fullmatch(token):
        raise ValidationFailedError("Malformed workspace token.", code="invalid_workspace_token")
    return hashlib.sha256(token.encode("ascii")).hexdigest()
