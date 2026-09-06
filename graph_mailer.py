"""Invio email via Microsoft Graph.

Riusa l'autenticazione a certificato gia' in uso per la lettura delle caselle
(deadline_monitor/graph_client.py): stessa app registrata, stesse variabili
MS_CLIENT_ID / MS_TENANT_ID / MS_CERT_PATH / MS_CERT_THUMBPRINT.

L'invio richiede il permesso applicativo Mail.Send sulla casella mittente.
"""

import logging
import os

import httpx

from deadline_monitor.graph_client import GRAPH_BASE, _get_access_token

logger = logging.getLogger(__name__)


class InvioError(RuntimeError):
    """Errore di invio: il messaggio e' gia' leggibile da un umano."""


def send_mail(mittente, destinatario, oggetto, html, salva_in_inviati=True,
              timeout=30):
    """Manda una mail HTML e torna l'id del messaggio salvato in Posta inviata.

    mittente     casella da cui parte (serve Mail.Send su quella casella)
    destinatario indirizzo singolo
    oggetto      subject
    html         corpo, gia' completo di <html>

    Alza InvioError con il messaggio di Graph se la chiamata fallisce: chi
    chiama lo registra e passa al destinatario successivo.
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

    url = f'{GRAPH_BASE}/users/{mittente.strip()}/sendMail'
    try:
        token = _get_access_token()
    except Exception as e:  # credenziali assenti o rifiutate
        raise InvioError(f'autenticazione Graph fallita: {e}') from e

    try:
        r = httpx.post(url, json=payload, timeout=timeout, headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        })
    except httpx.HTTPError as e:
        raise InvioError(f'rete: {e}') from e

    # sendMail risponde 202 senza corpo: non c'e' un id da leggere
    if r.status_code not in (200, 202):
        dettaglio = ''
        try:
            dettaglio = (r.json().get('error', {}).get('message') or '')[:300]
        except Exception:
            dettaglio = (r.text or '')[:300]
        raise InvioError(f'Graph {r.status_code}: {dettaglio}')

    logger.info('lettera inviata da %s a %s', mittente, destinatario)
    return r.headers.get('request-id', '')


def credenziali_pronte():
    """True se le variabili d'ambiente per Graph ci sono tutte."""
    attese = ('MS_CLIENT_ID', 'MS_TENANT_ID', 'MS_CERT_PATH', 'MS_CERT_THUMBPRINT')
    mancanti = [v for v in attese if not os.environ.get(v)]
    return (not mancanti), mancanti
