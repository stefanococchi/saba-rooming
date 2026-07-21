"""Microsoft Graph client for reading emails — adapted from saba-form."""

import logging
import os
from pathlib import Path

import httpx
import msal

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_msal_app = None


def _get_msal_app() -> msal.ConfidentialClientApplication:
    global _msal_app
    if _msal_app is None:
        cert_path = Path(os.environ["MS_CERT_PATH"])
        _msal_app = msal.ConfidentialClientApplication(
            client_id=os.environ["MS_CLIENT_ID"],
            authority=f"https://login.microsoftonline.com/{os.environ['MS_TENANT_ID']}",
            client_credential={
                "private_key": cert_path.read_text(),
                "thumbprint": os.environ["MS_CERT_THUMBPRINT"],
            },
        )
        logger.info("MSAL app initialized (tenant=%s)", os.environ["MS_TENANT_ID"])
    return _msal_app


def _get_access_token() -> str:
    app = _get_msal_app()
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" in result:
        return result["access_token"]
    error = result.get("error_description", result.get("error", "unknown"))
    raise RuntimeError(f"Graph token acquisition failed: {error}")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type": "application/json",
    }


# Campi richiesti per ogni messaggio (include body per il testo completo)
MESSAGE_SELECT = (
    "id,subject,from,toRecipients,receivedDateTime,"
    "internetMessageId,body,bodyPreview,isDraft"
)


def fetch_recent_emails(
    mailbox: str,
    since_iso: str,
    max_messages: int = 100,
) -> list[dict]:
    """Fetch emails received after since_iso from the given mailbox.

    Returns list of Graph message dicts with full body content.
    """
    messages: list[dict] = []
    url = f"{GRAPH_BASE}/users/{mailbox}/messages"
    params = {
        "$select": MESSAGE_SELECT,
        "$filter": f"receivedDateTime ge {since_iso}",
        "$orderby": "receivedDateTime desc",
        "$top": "50",
    }

    with httpx.Client(timeout=30.0) as client:
        while url and len(messages) < max_messages:
            resp = client.get(url, headers=_headers(), params=params)
            resp.raise_for_status()
            data = resp.json()
            params = None  # nextLink includes params

            for msg in data.get("value", []):
                if not msg.get("isDraft"):
                    messages.append(msg)

            url = data.get("@odata.nextLink", "")

    logger.info("Fetched %d emails from %s since %s", len(messages), mailbox, since_iso)
    return messages


CATEGORY_NAME = "Deadline Processed"


def _ensure_category(mailbox: str) -> None:
    """Create the 'Deadline Processed' category if it doesn't exist."""
    url = f"{GRAPH_BASE}/users/{mailbox}/outlook/masterCategories"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        existing = [c.get("displayName", "") for c in resp.json().get("value", [])]
        if CATEGORY_NAME not in existing:
            client.post(url, headers=_headers(), json={
                "displayName": CATEGORY_NAME,
                "color": "preset2",  # green
            }).raise_for_status()
            logger.info("Created category '%s'", CATEGORY_NAME)


def tag_email(mailbox: str, message_id: str) -> None:
    """Add 'Deadline Processed' category to a message."""
    _ensure_category(mailbox)
    url = f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}"
    with httpx.Client(timeout=15.0) as client:
        # Get current categories
        resp = client.get(url, headers=_headers(), params={"$select": "categories"})
        resp.raise_for_status()
        categories = resp.json().get("categories", [])
        if CATEGORY_NAME in categories:
            return
        categories.append(CATEGORY_NAME)
        # Update
        resp = client.patch(url, headers=_headers(), json={"categories": categories})
        resp.raise_for_status()
        logger.info("Tagged message %s with '%s'", message_id[:20], CATEGORY_NAME)
