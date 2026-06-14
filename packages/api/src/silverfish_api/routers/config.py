"""Email configuration endpoints: view (non-secret) settings and test sending.

The SMTP credentials are configured via environment (read at startup). These
routes expose the non-secret settings for a settings screen and a connectivity
test. They never accept or return the password. Whether sending is *available*
is reported by ``/health`` (``send_available``); the detail view here is for
display.
"""

from fastapi import APIRouter, HTTPException, Request, status

from silverfish_api.deps import MailerDep
from silverfish_api.errors import ERROR_500, ERROR_503
from silverfish_api.schemas import EmailConfigOut, EmailTestRequest

router = APIRouter(tags=["config"])


@router.get("/config/email", response_model=EmailConfigOut, responses={**ERROR_500})
def get_email_config(request: Request) -> EmailConfigOut:
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
