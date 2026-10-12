from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_optional_auth_session
from app.core.auth import SESSION_COOKIE_NAME, create_session_token
from app.core.config import Settings, get_settings
from app.schemas.auth import AuthSessionResponse, LoginRequest
from app.schemas.bootstrap import BootstrapInitRequest, BootstrapInitResponse, BootstrapStatusResponse
from app.services.admin_bootstrap_service import AdminAuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_admin_auth_service(settings: Settings = Depends(get_settings)) -> AdminAuthService:
    return AdminAuthService(settings)


@router.get("/session", response_model=AuthSessionResponse)
def get_auth_session(
    auth_session=Depends(get_optional_auth_session),
) -> AuthSessionResponse:
    if auth_session is None:
        return AuthSessionResponse(authenticated=False)

    return AuthSessionResponse(authenticated=True, username=auth_session.username)


@router.post("/login", response_model=AuthSessionResponse)
def login(
    payload: LoginRequest,
    response: Response,
    auth_service: AdminAuthService = Depends(_get_admin_auth_service),
) -> AuthSessionResponse:
    if not auth_service.verify_password(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    session_token = create_session_token(
        username=payload.username,
        secret=auth_service.get_session_secret(),
        max_age_seconds=auth_service.get_max_age_seconds(),
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=auth_service.get_max_age_seconds(),
        httponly=True,
        samesite="lax",
        secure=auth_service.settings.auth_cookie_secure,
        path="/",
    )
    return AuthSessionResponse(authenticated=True, username=payload.username)


@router.post("/logout", response_model=AuthSessionResponse)
def logout(response: Response) -> AuthSessionResponse:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", samesite="lax")
    return AuthSessionResponse(authenticated=False)


@router.get("/bootstrap/status", response_model=BootstrapStatusResponse)
def bootstrap_status(
    auth_service: AdminAuthService = Depends(_get_admin_auth_service),
) -> BootstrapStatusResponse:
    return BootstrapStatusResponse(**auth_service.status())


@router.post("/bootstrap/init", response_model=BootstrapInitResponse)
def bootstrap_init(
    payload: BootstrapInitRequest,
    auth_service: AdminAuthService = Depends(_get_admin_auth_service),
) -> BootstrapInitResponse:
    try:
        auth_service.bootstrap(payload.username, payload.password)
    except ValueError as exc:
        detail = str(exc)
        if "已初始化" in detail:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    return BootstrapInitResponse(initialized=True)
