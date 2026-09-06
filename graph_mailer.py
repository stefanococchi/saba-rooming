"""Invio email via Microsoft Graph.

Autenticazione applicativa (client credentials) con la stessa registrazione
gia' in uso: MS_CLIENT_ID e MS_TENANT_ID sono obbligatori, poi va bene
o il certificato (MS_CERT_PATH + MS_CERT_THUMBPRINT, se il file esiste
davvero) oppure MS_CLIENT_SECRET.

L'invio richiede il permesso applicativo Mail.Send sulla casella mittente,
con consenso dell'amministratore.
"""

import logging
import os
from pathlib import Path

import httpx
import msal

logger = logging.getLogger(__name__)

GRAPH_BASE = 'https://graph.microsoft.com/v1.0'

_app_msal = None
_modo = None


class InvioError(RuntimeError):
    """Errore di invio: il messaggio e' gia' leggibile da un umano."""


def _certificato():
    """Certificato utilizzabile, o None. Un percorso che non esiste vale
    quanto un certificato assente: si passa al client secret."""
    percorso = (os.environ.get('MS_CERT_PATH') or '').strip()
    impronta = (os.environ.get('MS_CERT_THUMBPRINT') or '').strip()
    if not percorso or not impronta:
        return None
    f = Path(percorso)
    if not f.is_file():
        logger.warning('MS_CERT_PATH punta a un file inesistente (%s): '
                       'uso il client secret', percorso)
        return None
    return {'private_key': f.read_text(), 'thumbprint': impronta}


def _credenziale():
    """Torna (credenziale per msal, descrizione del modo) oppure (None, None)."""
    cert = _certificato()
    if cert:
        return cert, 'certificato'
    segreto = (os.environ.get('MS_CLIENT_SECRET') or '').strip()
    if segreto:
        return segreto, 'client secret'
    return None, None


def stato_credenziali():
    """(pronte, mancanti, modo) — cosa manca e come ci si autentica."""
    mancanti = [v for v in ('MS_CLIENT_ID', 'MS_TENANT_ID')
                if not (os.environ.get(v) or '').strip()]
    cred, modo = _credenziale()
    if not cred:
        mancanti.append('MS_CLIENT_SECRET (oppure MS_CERT_PATH valido + '
                        'MS_CERT_THUMBPRINT)')
    return (not mancanti), mancanti, modo


def credenziali_pronte():
    """Compatibilita': (pronte, mancanti)."""
    pronte, mancanti, _ = stato_credenziali()
    return pronte, mancanti


def _token():
    global _app_msal, _modo
    if _app_msal is None:
        cred, modo = _credenziale()
        if not cred:
            raise InvioError('credenziali Graph assenti')
        _app_msal = msal.ConfidentialClientApplication(
            client_id=os.environ['MS_CLIENT_ID'],
            authority=f"https://login.microsoftonline.com/{os.environ['MS_TENANT_ID']}",
            client_credential=cred,
        )
        _modo = modo
        logger.info('MSAL pronto per invio (%s)', modo)
    r = _app_msal.acquire_token_for_client(
        scopes=['https://graph.microsoft.com/.default'])
    if 'access_token' in r:
        return r['access_token']
    raise InvioError('token rifiutato: ' +
                     str(r.get('error_description') or r.get('error') or r))


def send_mail(mittente, destinatario, oggetto, html, salva_in_inviati=True,
              timeout=30):
    """Manda una mail HTML dalla casella indicata.

    Alza InvioError con il messaggio di Graph se fallisce: chi chiama lo
    registra e passa al destinatario successivo.
    """
    if not (mittente or '').strip():
        raise InvioError('casella mittente non configurata')
    if not (destinatario or '').strip():
        raise InvioError('destinatario mancante')

    payload = {
        'message': {
            'subject': oggetto,
            'body': {'contentType': 'HTML', 'content': html},
            'toRecipients': [{'emailAddress': {'address': destinatario.strip()}}],
        },
        'saveToSentItems': bool(salva_in_inviati),
    }

    token = _token()
    url = f'{GRAPH_BASE}/users/{mittente.strip()}/sendMail'
    try:
        r = httpx.post(url, json=payload, timeout=timeout, headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        })
    except httpx.HTTPError as e:
        raise InvioError(f'rete: {e}') from e

    # sendMail risponde 202 senza corpo: non c'e' un id da leggere
    if r.status_code not in (200, 202):
        try:
            dettaglio = (r.json().get('error', {}).get('message') or '')[:300]
        except Exception:
            dettaglio = (r.text or '')[:300]
        raise InvioError(f'Graph {r.status_code}: {dettaglio}')

    logger.info('lettera inviata da %s a %s', mittente, destinatario)
    return r.headers.get('request-id', '')
