# Lettere di convocazione — dove siamo

Aggiornato: **7 settembre 2026**, mattina.
Ultimo commit: `1e388fb`. Tutto pushato su `main`, working tree pulito.

---

## Il blocco e' stato tolto — 7 settembre 2026

**`Mail.Send` applicativo c'e' ed e' concesso.** Il permesso mancava perche'
sull'app registration `saba-form` la riga `Mail.Send` esisteva solo di tipo
**Delegato**, che nei token applicativi non compare. Ne e' stata aggiunta una
seconda di tipo **Applicazione** ("Send mail as any user") e dato il consenso
amministratore. Ora Microsoft Graph ha 13 autorizzazioni e `Mail.Send` compare
due volte, come gia' faceva `Mail.Read`.

Il token adesso dice `['Mail.Read', 'Mail.Send']`. Si ricontrolla cosi':

```bash
/c/Users/stefa/PythonProjects/venv/Scripts/python.exe - <<'PY'
import os, json, base64
for l in open('.env', encoding='utf-8'):
    if '=' in l and not l.startswith('#'):
        k, v = l.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"\''))
import graph_mailer
t = graph_mailer._token(); p = t.split('.')[1]; p += '=' * (-len(p) % 4)
print(sorted(json.loads(base64.urlsafe_b64decode(p)).get('roles', [])))
PY
```

**`evento.eps@sabae20.it` e' una casella vera**, non un alias: Graph ne legge le
cartelle (200). Il dubbio su `MailboxNotEnabledForRESTAPI` e' chiuso.

### Cosa resta da fare per spedire

1. **Redeploy su Railway** — l'istanza in produzione ha ancora in mano il token
   vecchio, senza `Mail.Send`. Dura fino a un'ora.
2. **Invia prova** dalle lettere: due mail su `evento.eps@sabae20.it`, una di chi
   vola e una di chi arriva in pullman. Mai fatta finora.
3. L'invio vero resta spento dall'interruttore nell'ingranaggio.

### Debito rimasto su Azure

`saba-rooming` si presenta a Microsoft con l'identita' di **`saba-form`**:
`MS_CLIENT_ID` nel `.env` e' l'app registration di quell'altro progetto, e
`MS_CERT_PATH` punta ancora al certificato di un vecchio PC
(`C:\Users\ACER\PycharmProjects\saba-form\...`), che infatti non esiste.

Conseguenze: i due progetti condividono un segreto solo, `saba-form` eredita il
permesso di spedire da qualsiasi casella del tenant, e nei log di Exchange le
lettere risultano spedite da "saba-form".

Deciso il 7 settembre di **rimandare**: prima le lettere, poi una registrazione
dedicata `saba-rooming` con il solo `Mail.Send`. Si cambiano due variabili nel
`.env` e su Railway, il codice non si tocca.

Se si vuole restringere l'invio alla sola casella dell'evento senza separare le
identita', si fa lato Exchange con una *Application Access Policy*.

---

## Dati da riempire prima di spedire davvero

Stanno tutti in `app.py`, in cima al blocco delle lettere.

| costante | cosa manca | dove si vede |
|---|---|---|
| `PULLMAN_CATANIA['indirizzo']` | via e civico della sede EPS di Catania | "Punto di ritrovo: Sede di Catania – …" |
| `PULLMAN_CATANIA['ritrovo']` | orario | riga "Orario di ritrovo" |
| `PULLMAN_CATANIA['partenza']` | orario | riga "Orario di partenza del pullman" |
| `PULLMAN_CATANIA['arrivo']` | orario arrivo al resort | riga "Arrivo previsto al Mangia's Pollina Resort" |
| `PULLMAN_CATANIA['riconoscimento']` | come si riconosce l'assistente | "…facilmente riconoscibile grazie a …" |
| `BAGAGLIO_MISURE` | misure del bagaglio a mano | frase del bagaglio, in **tutte** le lettere |
| `EVENTO['contatto_tel']` | telefono del referente | blocco contatti in fondo |

L'indirizzo della sede di Catania **non è pubblico**: ho cercato su
equans.com, ocis-equans.it e in giro, si trovano solo Milano (Via
Stephenson 73) e Verona (Via Francia 21/C). Va chiesto internamente.

Finché i campi del pullman sono vuoti, ogni lettera di Catania porta il
warning "orari del pullman da Catania da definire" e le righe non
compaiono — nessun orario inventato.

**Manca del tutto il rientro dei 62 di Catania.** Oggi la loro lettera
racconta solo l'andata.

---

## Ospiti da sistemare

**14 con dati mancanti** (vengono saltati dall'invio, con il motivo):

- senza email: Bianchetti Umberto, Mammoliti Claudio, Spina Lorenzo
- senza volo: Bisignano (Parigi), Sabatino (Francoforte), Motta Aurelio
- record incompleti, senza nemmeno la sede: CONSOLI, FRANCESE, LANDOLINA,
  Martucci, PAPPALARDO, RICCIARDOLO
- **FINOCCHIARO Nunzio** e **GIAMBIASI Lucia**: in nota c'è scritto che
  hanno chiesto di essere cancellati, ma risultano ancora attivi. Vanno
  eliminati, non sistemati.

---

## Decisioni rimaste in sospeso

1. **Pulire `restrizioni_alimentari` a database?** 18 righe contengono
   `'altro - scrivilo nelle note'`, che è un segnaposto del form. In lettera
   non escono più (`DIETE_VUOTE` le filtra), ma a database ci sono ancora.
   **Prima di cancellare**: almeno 2 di questi hanno l'allergia vera scritta
   in `note_form` — #16 Bisconti *"allergico, pesca e albicocca"* e #137
   Salamone *"mais, cocco, mandorla, cetriolo, pistacchio, funghi, frutta
   secca"*. Quelle allergie **non sono** nel campo che va all'hotel.
2. **Export voli**: `app.py:2818` stampa ancora la colonna "Pres. 11", ormai
   ✕ per tutti. Anche il selettore colonne in `index.html` la elenca.
3. **`note_form`** era pieno di roba utile alla segreteria: è uscito dalla
   lettera, ma nessuno lo sta più leggendo da nessuna parte.

---

## Cos'è stato fatto oggi

| commit | cosa |
|---|---|
| `e5183cb` | export cene: esclusi i NO SHOW |
| `0879c40` | lettere: logo Equans, via note interne e note del form, evento fino al 10 |
| `a1e8fff` | periodo "8–10 ottobre 2026" |
| `b653176` | contatto `evento.eps@sabae20.it` |
| `dcb6755` | il tasto "Testo introduttivo" non apriva niente: mancava la funzione |
| `24e874c` | via camera assegnata; niente warning volo per chi arriva da Catania |
| `61b7e5f` | nuovo testo EPS Sicilia Experience dentro l'HTML |
| `f50db42` | filtrati i segnaposto del form fra le esigenze alimentari |
| `55d5b04` | in fondo solo "powered by sabae20" |
| `1fa14ab` | sezione pullman da Catania al posto dei voli |
| `839e9c9` | sosta e bagaglio a mano anche nel pullman |
| `730a97d` | palette e font di equans.com |
| `6b63a38` | invio via MS Graph, spento di default |
| `1bad391` | pulsanti di invio e interruttore dentro l'app |
| `1e388fb` | autenticazione Graph col client secret |

### Come funziona l'invio

- `graph_mailer.py` — `send_mail()` via Graph. Prova il certificato solo se
  il file esiste davvero (`MS_CERT_PATH` punta a un vecchio PC e non c'è),
  altrimenti usa `MS_CLIENT_SECRET`.
- Tabella `impostazioni`: mittente, indirizzo delle prove e interruttore.
  **Niente variabili su Railway**, si cambia tutto dall'ingranaggio nella
  finestra delle lettere.
- Tabella `lettere_invii`: una riga per ogni tentativo. Serve a non spedire
  due volte — chi ha già ricevuto viene saltato con "già inviata".
- `POST /api/rooming/lettere/prova` · `/invia` · `GET /invii` · `/config`
- L'invio vero risponde 403 finché l'interruttore è spento.

### Note tecniche per chi riprende

- Il venv è **`C:\Users\stefa\PythonProjects\venv`**, non nel progetto.
- **Non c'è node** su questa macchina: il JS l'ho fatto validare al motore di
  Chrome con `new Function`.
- Gli **screenshot del browser non funzionano** su portal.azure.com e
  equans.com: l'estensione va in timeout sull'iniezione. Il JavaScript sulla
  stessa scheda invece gira.
- `db.create_all()` crea da solo le tabelle nuove al riavvio.
