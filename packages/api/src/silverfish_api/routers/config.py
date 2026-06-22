"""Email configuration endpoints: view (non-secret) settings and test sending.

The SMTP credentials are configured via environment (read at startup). These
routes expose the non-secret settings for a settings screen and a connectivity
test. They never accept or return the password. Whether sending is *available*
is reported by ``/health`` (``send_available``); the detail view here is for
display.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from silverfish_api.config_store import build_send_chain, read_config, write_config
from silverfish_api.deps import MailerDep
from silverfish_api.errors import ERROR_422, ERROR_500, ERROR_503
from silverfish_api.schemas import ConfigUpdate, EmailConfigOut, EmailTestRequest

router = APIRouter(tags=["config"])


@router.get("/config", responses={**ERROR_500})
def get_config(
    request: Request,
    keys: Annotated[
        list[str],
        Query(description="Config keys to read. Unknown keys are omitted."),
    ],
) -> dict[str, str | None]:
    """Return the requested config values (None when unset).

    Only known keys are returned; secret keys (the SMTP password) read back as a
    masked placeholder when set, never their value.
    """
    return read_config(request.app.state.system_db, keys)


@router.post("/config", responses={**ERROR_422, **ERROR_500})
def set_config(payload: ConfigUpdate, request: Request) -> dict[str, str | None]:
    """Set one or more config values and return their (masked) readback.

    Only the provided keys change; others are untouched, so a UI can edit just
    ``kindle_email`` without resending SMTP. Unknown keys → 422. After a write,
    the mailer is rebuilt so SMTP changes take effect without a restart.
    """
    try:
        written = write_config(request.app.state.system_db, payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # If any SMTP key changed, rebuild the mailer + send service from env+store
    # and swap them in, so the change takes effect without a restart.
    if any(k.startswith("smtp_") for k in written):
        state = request.app.state
        mailer, send_service = build_send_chain(
            state.settings, state.system_db, state.repository, state.storage
        )
        state.mailer = mailer
        state.send_service = send_service

    return read_config(request.app.state.system_db, written)


@router.get("/config/email", response_model=EmailConfigOut, responses={**ERROR_500})
def get_email_config(request: Request) -> EmailConfigOut:
    """Return the non-secret SMTP settings for display.

    Reports whether SMTP is `configured` along with `host`, `port`,
    `from_address` (falling back to the username when no explicit from is set)
    and `security`. The password is never read or returned.
    """
    settings = request.app.state.settings
    return EmailConfigOut(
        configured=settings.smtp_configured,
        host=settings.smtp_host,
        port=settings.smtp_port,
        from_address=settings.smtp_from or settings.smtp_username,
        security=settings.smtp_security,
    )


@router.post(
    "/config/email/test",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**ERROR_503, **ERROR_500},
)
def test_email_config(payload: EmailTestRequest, mailer: MailerDep) -> None:
    """Send a test email to verify SMTP connectivity.

    Sends a test message to `to_email` and returns 204 on success. Responds 503
    if SMTP is not configured, or 502 if the connection, authentication or send
    fails.
    """
    if mailer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMTP is not configured",
        )
    try:
        mailer.test(payload.to_email)
    except OSError as exc:
        # Connection/auth failures surface as a bad gateway-style error, not 500.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"SMTP test failed: {exc}",
        ) from exc
