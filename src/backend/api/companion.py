"""Authenticated desktop API for the docked Stacks companion."""

from fastapi import APIRouter
from src.backend.api import office

router = APIRouter(prefix="/companion", tags=["companion"])


@router.post("/assist", response_model=office.AssistResult)
def assist(request: office.AssistRequest) -> office.AssistResult:
    """Run the same grounded document action used by the Office pane.

    The companion is part of the authenticated desktop app, while the Office
    pane reaches the equivalent operation through its separate HTTPS bridge.
    Keeping one request and response contract makes answers and citations
    consistent between both surfaces.
    """
    return office.assist(request)
