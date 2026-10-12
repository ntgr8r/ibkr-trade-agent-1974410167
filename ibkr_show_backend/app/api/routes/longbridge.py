from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_longbridge_external_data_client, require_authenticated_session
from app.schemas.longbridge import (
    LongbridgeBenchmarkCandlesResponse,
    LongbridgeCandlesResponse,
    LongbridgeHealthResponse,
    LongbridgeMacroNewsResponse,
    LongbridgeNewsResponse,
)
from app.services.longbridge_service import LongbridgeExternalDataClient, LongbridgeExternalDataError, LongbridgeUnavailableError

router = APIRouter(
    prefix="/longbridge",
    tags=["longbridge"],
    dependencies=[Depends(require_authenticated_session)],
)


@router.get("/health", response_model=LongbridgeHealthResponse)
def get_longbridge_health(
    service: LongbridgeExternalDataClient = Depends(get_longbridge_external_data_client),
) -> LongbridgeHealthResponse:
    return LongbridgeHealthResponse(**service.health())


@router.get("/candles", response_model=LongbridgeCandlesResponse)
def get_longbridge_candles(
    symbol: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    period: str = Query(default="day"),
    adjust_type: str = Query(default="forward"),
    service: LongbridgeExternalDataClient = Depends(get_longbridge_external_data_client),
) -> LongbridgeCandlesResponse:
    try:
        return service.get_candles(symbol=symbol, start=start, end=end, period=period, adjust_type=adjust_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LongbridgeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except LongbridgeExternalDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/benchmark-candles", response_model=LongbridgeBenchmarkCandlesResponse)
def get_longbridge_benchmark_candles(
    start: str = Query(...),
    end: str = Query(...),
    symbols: str = Query(default="SPY,QQQ,SMH"),
    period: str = Query(default="day"),
    service: LongbridgeExternalDataClient = Depends(get_longbridge_external_data_client),
) -> LongbridgeBenchmarkCandlesResponse:
    try:
        benchmarks = service.get_benchmark_candles(symbols=symbols, start=start, end=end, period=period)
        return LongbridgeBenchmarkCandlesResponse(start=start, end=end, period=period.strip().lower(), benchmarks=benchmarks)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LongbridgeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except LongbridgeExternalDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/news", response_model=LongbridgeNewsResponse)
def get_longbridge_news(
    symbol: str = Query(...),
    limit: int = Query(default=20, ge=1, le=50),
    service: LongbridgeExternalDataClient = Depends(get_longbridge_external_data_client),
) -> LongbridgeNewsResponse:
    try:
        return service.get_news(symbol=symbol, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LongbridgeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except LongbridgeExternalDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/macro-news", response_model=LongbridgeMacroNewsResponse)
def get_longbridge_macro_news(
    keyword: str = Query(default="macro economy"),
    limit: int = Query(default=20, ge=1, le=50),
    service: LongbridgeExternalDataClient = Depends(get_longbridge_external_data_client),
) -> LongbridgeMacroNewsResponse:
    try:
        return service.search_macro_news(keyword=keyword, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LongbridgeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except LongbridgeExternalDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
