from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from src.backend.api.deps import require_course
from src.backend.artifacts.mind_maps import MapStudyResult, study
from src.backend.common import provider, usage_repo
from src.backend.common.artifacts_repo import StaleVersionError
from src.backend.common.schemas.map_study import MapStudyRequest

router = APIRouter(tags=["mind_maps"])


@router.post("/courses/{course_id}/mind-map/study", response_model=MapStudyResult)
def study_topic(course_id: UUID, payload: MapStudyRequest) -> MapStudyResult:
    require_course(course_id)
    try:
        return study(course_id, payload)
    except LookupError as err:
        raise HTTPException(404, str(err)) from err
    except StaleVersionError as err:
        raise HTTPException(409, str(err)) from err
    except (ValueError, ValidationError) as err:
        raise HTTPException(422, str(err)) from err
    except provider.ProviderUnavailableError as err:
        raise HTTPException(503, str(err)) from err
    except usage_repo.BudgetExceededError as err:
        raise HTTPException(402, str(err)) from err
