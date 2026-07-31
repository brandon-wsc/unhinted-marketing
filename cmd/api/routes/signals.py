from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.memory.database import get_db
from internal.memory.models import User
from internal.memory.repos import list_top_signals
from schemas.perception import SignalResponse, TopSignalsResponse

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/top", response_model=TopSignalsResponse)
async def top_signals(
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    region: str = "HK",
) -> TopSignalsResponse:
    rows = await list_top_signals(db, limit=limit, region=region)
    signals = [
        SignalResponse(
            signal_id=r.signal_id,
            source=r.source,
            title=r.title,
            url=r.url,
            excerpt=r.excerpt,
            region=r.region,
            metrics=r.metrics or {},
            ingested_at=r.ingested_at,
        )
        for r in rows
    ]
    return TopSignalsResponse(region=region, count=len(signals), signals=signals)
