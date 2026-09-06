# Lettere di convocazione — dove siamo

Aggiornato: **6 settembre 2026**, fine giornata.
Ultimo commit: `1e388fb`. Tutto pushato su `main`, working tree pulito.

---

## Il blocco che ferma tutto

**L'app non ha il permesso per spedire.** Ho letto il token di Microsoft alle
15:40 UTC di oggi: contiene solo `Mail.Read`, `Mail.Send` non c'è.

Finché non c'è, il pulsante "Invia prova" risponde `403 Access denied`.
Tutto il resto è pronto e provato.

### Cosa controllare, nell'ordine

Portale: **portal.azure.com → Microsoft Entra ID → Registrazioni app →
saba-form → Autorizzazioni API**. Collegamento diretto:

```
https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationMenuBlade/~/CallAnAPI/appId/548a2cbb-d4ab-4caa-80e6-056841cf48d5
```

1. **La riga `Mail.Send` che tipo ha?** Deve dire **Applicazione**.
   Se dice **Delegato** è inutile: nei token applicativi i permessi delegati
   non compaiono. Va rimosso e rifatto scegliendo "Autorizzazioni
   applicazione", che il portale *non* preseleziona.
2. **Lo stato è verde?** Serve "Concesso per…". Il triangolo arancione
   significa che manca il pulsante **Concedi consenso amministratore**.
3. **È l'app giusta?** In Panoramica, ID applicazione (client) deve essere
   `548a2cbb-d4ab-4caa-80e6-056841cf48d5`. Tenant
   `3ccb04bd-31a9-4f86-9125-2ff8ea92a66f`.

### Come verificare senza spedire niente

```bash
/c/Users/stefa/PythonProjects/venv/Scripts/python.exe - <<'EOF'
import os, json, base64
for l in open('.env', encoding='utf-8'):
    if '=' in l and not l.startswith('#'):
        k, v = l.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"\''))
import graph_mailer
t = graph_mailer._token(); p = t.split('.')[1]; p += '=' * (-len(p) % 4)
print(sorted(json.loads(base64.urlsafe_b64decode(p)).get('roles', [])))
EOF
```

Deve stampare `['Mail.Read', 'Mail.Send']`. Dopo il consenso serve un
**redeploy su Railway**: il token in circolo dura fino a un'ora.

### Poi

Apri le lettere → **Invia prova**. Arrivano due mail su
`evento.eps@sabae20.it`, una di chi vola e una di chi arriva in pullman.

Dubbio ancora aperto: **`evento.eps@sabae20.it` è una casella vera o un
alias?** Se è un alias, `sendMail` risponde `404
MailboxNotEnabledForRESTAPI`. In quel caso si cambia il mittente
dall'ingranaggio, senza toccare il codice.

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
