import os
import json
from datetime import datetime
from io import BytesIO

from flask import (Flask, render_template, request, jsonify,
                   send_file, redirect, url_for)
from dotenv import load_dotenv

load_dotenv()

from models import (db, Guest, RoomContract, EmailLog,
                     PartiviaQuote, PartiviaRoomRate,
                     PartiviaMeetingRoom, PartiviaFBOption)


def _parse_bool(val):
    """Converte vari formati in booleano."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ('1', 'true', 'sì', 'si', 'yes', 'x', 'v', '✓')


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 'postgresql://postgres:123456@localhost:5432/saba_rooming'
    ).replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

    db.init_app(app)

    with app.app_context():
        db.create_all()
        # Seed contratti camere se non esistono
        if RoomContract.query.count() == 0:
            CONTRATTI = [
                ('DUS Standard',          36, 218.50, 230.00),
                ('DUS Superior',          50, 266.00, 280.00),
                ('DUS Superior Sea View', 10, 289.75, 305.00),
                ('DUS Deluxe',            30, 308.75, 325.00),
                ('DUS Deluxe Sea View',   31, 332.50, 350.00),
            ]
            for notte in (8, 9):
                for tipo, disp, netta, lorda in CONTRATTI:
                    db.session.add(RoomContract(
                        tipo=tipo, disponibili=disp,
                        tariffa_netta=netta, tariffa_lorda=lorda, notte=notte))
            db.session.commit()

    # ── LANDING PAGE ────────────────────────────────────────────────────────

    @app.route('/')
    def landing():
        return render_template('landing.html')

    # ── PAGINA ROOMING ──────────────────────────────────────────────────────

    @app.route('/rooming')
    def index():
        guests = Guest.query.order_by(Guest.cognome, Guest.nome).all()
        return render_template('index.html', guests=guests)

    # ── CRUD API ─────────────────────────────────────────────────────────────

    # Campi stringa editabili
    GUEST_STR_FIELDS = (
        'cognome', 'nome', 'email', 'telefono', 'sede_lavoro',
        'volo_arrivo', 'volo_partenza',
        'aeroporto_partenza', 'aeroporto_arrivo',
        'pickup_bus_andata', 'pickup_bus_ritorno',
        'divide_stanza_con', 'restrizioni_alimentari',
        'tipo_camera', 'camera_assegnata', 'note_form', 'note',
    )
    GUEST_BOOL_FIELDS = (
        'presenza_8', 'presenza_9', 'presenza_10', 'presenza_11',
        'parcheggio_linate', 'parcheggio_hotel',
    )

    @app.post('/api/guest')
    def add_guest():
        data = request.get_json()
        kwargs = {'source': 'manual'}
        for f in GUEST_STR_FIELDS:
            v = data.get(f, '').strip() if data.get(f) else None
            kwargs[f] = v
        for f in GUEST_BOOL_FIELDS:
            kwargs[f] = _parse_bool(data.get(f))
        g = Guest(**kwargs)
        if not g.cognome:
            return jsonify(ok=False, error='Cognome obbligatorio'), 400
        db.session.add(g)
        db.session.commit()
        return jsonify(ok=True, id=g.id)

    @app.put('/api/guest/<int:gid>')
    def update_guest(gid):
        g = Guest.query.get_or_404(gid)
        data = request.get_json()
        for field in GUEST_STR_FIELDS:
            if field in data:
                setattr(g, field, data[field].strip() if data[field] else None)
        for field in GUEST_BOOL_FIELDS:
            if field in data:
                setattr(g, field, _parse_bool(data[field]))
        g.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(ok=True)

    @app.delete('/api/guest/<int:gid>')
    def delete_guest(gid):
        g = Guest.query.get_or_404(gid)
        db.session.delete(g)
        db.session.commit()
        return jsonify(ok=True)

    # ── IMPORT XLSX (LLM-guided) ─────────────────────────────────────────────

    @app.post('/api/import/preview')
    def import_preview():
        """Step 1: Upload XLSX, LLM analizza headers e prime righe, propone mapping."""
        import anthropic

        f = request.files.get('file')
        if not f or not f.filename.endswith(('.xlsx', '.xls')):
            return jsonify(ok=False, error='File XLSX richiesto'), 400

        from openpyxl import load_workbook
        wb = load_workbook(f, read_only=True, data_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return jsonify(ok=False, error='File vuoto'), 400

        # Leggi header + prime 5 righe di dati per contesto
        header = [str(c).strip() if c else '' for c in rows[0]]
        sample_rows = []
        for row in rows[1:6]:
            sample_rows.append([str(c).strip() if c else '' for c in row])

        # Prepara tutte le righe dati per salvarle in sessione
        all_rows = []
        for row in rows[1:]:
            all_rows.append([str(c).strip() if c else '' for c in row])

        # Chiedi a Claude di mappare le colonne
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            return jsonify(ok=False, error='ANTHROPIC_API_KEY non configurata'), 500

        system_prompt = """Sei un assistente che analizza file Excel di rooming list per un evento che si svolge dall'8 all'11 ottobre.

Ti vengono dati gli header delle colonne e alcune righe di esempio.

STEP 1 — MAPPING COLONNE
Mappa ogni colonna del file a uno dei seguenti campi del database:

- cognome, nome (o "nome_completo" se in una sola colonna, con campo "formato": "nome cognome" o "cognome nome")
- email, telefono
- sede_lavoro (città/sede di lavoro, es. MILANO, CATANIA)
- presenza_8, presenza_9, presenza_10, presenza_11 (giorni 8-11 ottobre)
- volo_arrivo (volo di andata), volo_partenza (volo di ritorno)
- aeroporto_partenza, aeroporto_arrivo
- pickup_bus_andata (orario pickup bus andata), pickup_bus_ritorno (orario pickup bus ritorno)
- parcheggio_linate (booleano)
- parcheggio_hotel (booleano)
- divide_stanza_con (con chi condivide la stanza)
- restrizioni_alimentari (allergie, intolleranze, diete religiose, ecc.)
- tipo_camera (singola, doppia, twin, suite, etc.)
- note_form (note inserite dall'utente nel form di registrazione)
- note (note operative/gestionali)
- IGNORA: colonne che non servono

STEP 2 — INTERPRETAZIONE DATI (FONDAMENTALE)
I dati nel file possono NON corrispondere 1:1 ai campi. Devi capire il significato reale.

REGOLE DI INTERPRETAZIONE DATE/PRESENZE:
- L'evento è dall'8 all'11 ottobre. I giorni sono: 8, 9, 10, 11.
- "arrivo gio 8/10" o "arrivo 8 ott" = la persona ARRIVA il giorno 8 ottobre
- "partenza ven 10/10" o "riparte 10" = la persona RIPARTE il giorno 10 ottobre
- Se una persona arriva il giorno X e riparte il giorno Y, è PRESENTE tutti i giorni da X a Y-1 (l'ultimo giorno riparte, non è presente all'evento)
  - Esempio: arrivo 8, partenza 10 → presenza_8=sì, presenza_9=sì, presenza_10=no, presenza_11=no
- Se c'è solo "arrivo 8" senza partenza, assumi che resti fino alla fine (presenza_8=sì, presenza_9=sì, presenza_10=sì, presenza_11=sì)
- "8/10" in una colonna di date può significare "8 ottobre" (giorno/mese) — NON "dall'8 al 10"
- Se ci sono colonne separate per ogni giorno (es. "8 ott", "9 ott"), mappale direttamente a presenza_8, presenza_9, ecc.
- Se c'è UNA sola colonna con date di arrivo/partenza, NON mapparla a un singolo campo presenza. Segnalala come "date_soggiorno" e nella sezione "trasformazioni" spiega come derivare le presenze.

REGOLE GENERALI:
- Analizza i DATI nelle righe, non solo gli header
- Se non sei sicuro, mappa come IGNORA
- Colonne vuote o con solo formattazione → IGNORA

Rispondi SOLO con JSON valido:
{
  "mapping": {
    "0": {"campo": "cognome", "header_originale": "Surname", "confidenza": "alta"},
    "1": {"campo": "nome_completo", "header_originale": "Nome", "confidenza": "alta", "formato": "nome cognome"}
  },
  "trasformazioni": [
    {
      "descrizione": "La colonna X contiene date di arrivo nel formato 'gio 8/10'. Derivare presenza_8..11 dal range arrivo-partenza.",
      "colonne_coinvolte": [3, 5],
      "tipo": "date_to_presenze"
    }
  ],
  "note_mapping": "spiegazione breve"
}

Le chiavi di "mapping" sono gli indici delle colonne (0, 1, 2, ...).
"confidenza" può essere: "alta", "media", "bassa".
"trasformazioni" è opzionale — usalo quando i dati richiedono interpretazione oltre al semplice mapping."""

        sample_text = f"HEADER: {json.dumps(header, ensure_ascii=False)}\n\n"
        sample_text += "RIGHE DI ESEMPIO:\n"
        for i, row in enumerate(sample_rows):
            sample_text += f"Riga {i+1}: {json.dumps(row, ensure_ascii=False)}\n"

        client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=2048,
                system=system_prompt,
                messages=[{'role': 'user', 'content': sample_text}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith('```'):
                raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
                if raw.endswith('```'):
                    raw = raw[:-3]
                raw = raw.strip()

            mapping_result = json.loads(raw)

            inp = response.usage.input_tokens
            out = response.usage.output_tokens
            cost = (inp * 0.80 + out * 4.00) / 1_000_000

            # Salva i dati in un file temporaneo per lo step 2
            import tempfile, uuid
            import_id = str(uuid.uuid4())
            tmp_path = os.path.join(tempfile.gettempdir(), f'saba_import_{import_id}.json')
            with open(tmp_path, 'w') as tf:
                json.dump({'header': header, 'rows': all_rows}, tf, ensure_ascii=False)

            return jsonify(
                ok=True,
                import_id=import_id,
                header=header,
                mapping=mapping_result.get('mapping', {}),
                trasformazioni=mapping_result.get('trasformazioni', []),
                note_mapping=mapping_result.get('note_mapping', ''),
                sample_rows=sample_rows,
                total_rows=len(all_rows),
                usage={'input': inp, 'output': out, 'cost_eur': round(cost * 0.92, 4)},
            )

        except json.JSONDecodeError:
            return jsonify(ok=False, error=f'Risposta LLM non valida: {raw[:300]}'), 500
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    @app.post('/api/import/confirm')
    def import_confirm():
        """Step 2: Usa il LLM per interpretare OGNI riga e produrre i record Guest."""
        import anthropic, tempfile

        data = request.get_json()
        import_id = data.get('import_id')
        mapping = data.get('mapping', {})
        trasformazioni = data.get('trasformazioni', [])

        if not import_id:
            return jsonify(ok=False, error='import_id mancante'), 400

        tmp_path = os.path.join(tempfile.gettempdir(), f'saba_import_{import_id}.json')
        if not os.path.exists(tmp_path):
            return jsonify(ok=False, error='Sessione di import scaduta. Ricarica il file.'), 400

        with open(tmp_path) as tf:
            file_data = json.load(tf)

        header = file_data['header']
        rows = file_data['rows']

        # Controlla se servono trasformazioni complesse (date → presenze)
        needs_llm = any(t.get('tipo') == 'date_to_presenze' for t in trasformazioni)

        if needs_llm:
            # Manda TUTTE le righe al LLM per interpretazione
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if not api_key:
                return jsonify(ok=False, error='ANTHROPIC_API_KEY non configurata'), 500

            # Costruisci mapping descrittivo
            mapping_desc = {}
            for idx_str, info in mapping.items():
                campo = info.get('campo', 'IGNORA') if isinstance(info, dict) else info
                if campo != 'IGNORA':
                    mapping_desc[header[int(idx_str)]] = campo

            system_prompt = f"""Sei un assistente che converte righe di un Excel in record JSON per un database di rooming.

L'evento è dall'8 all'11 ottobre.

Mapping colonne stabilito: {json.dumps(mapping_desc, ensure_ascii=False)}

Trasformazioni richieste: {json.dumps(trasformazioni, ensure_ascii=False)}

Per ogni riga, produci un oggetto JSON con TUTTI questi campi:
- cognome (MAIUSCOLO), nome, email, telefono, sede_lavoro
- presenza_8, presenza_9, presenza_10, presenza_11 (true/false)
- volo_arrivo, volo_partenza
- aeroporto_partenza, aeroporto_arrivo
- pickup_bus_andata, pickup_bus_ritorno
- parcheggio_linate (true/false), parcheggio_hotel (true/false)
- divide_stanza_con, restrizioni_alimentari
- tipo_camera, note_form, note

REGOLE PRESENZE:
- Se arriva giorno X e parte giorno Y: presente da X a Y-1
- "arrivo gio 8/10" = arriva l'8 ottobre (gio=giovedì, 8/10=8 ottobre)
- "partenza 10/10" = parte il 10 ottobre
- Se solo arrivo senza partenza: presente dall'arrivo fino all'11
- Se solo partenza senza arrivo: presente dall'8 fino a partenza-1
- Campi non presenti nel file → null (stringhe) o false (booleani)
- Righe vuote (senza cognome/nome) → skippa, non includerle

Rispondi SOLO con JSON valido (array di oggetti), niente markdown."""

            # Manda a blocchi di 50 righe per non superare i limiti
            all_guests = []
            CHUNK = 50
            client = anthropic.Anthropic(api_key=api_key)
            total_inp, total_out = 0, 0

            for chunk_start in range(0, len(rows), CHUNK):
                chunk = rows[chunk_start:chunk_start + CHUNK]
                rows_text = f"HEADER: {json.dumps(header, ensure_ascii=False)}\n\n"
                for i, row in enumerate(chunk):
                    rows_text += f"Riga {chunk_start + i + 1}: {json.dumps(row, ensure_ascii=False)}\n"

                response = client.messages.create(
                    model='claude-haiku-4-5-20251001',
                    max_tokens=4096,
                    system=system_prompt,
                    messages=[{'role': 'user', 'content': rows_text}],
                )
                raw = response.content[0].text.strip()
                if raw.startswith('```'):
                    raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
                    if raw.endswith('```'):
                        raw = raw[:-3]
                    raw = raw.strip()

                chunk_guests = json.loads(raw)
                if isinstance(chunk_guests, dict) and 'guests' in chunk_guests:
                    chunk_guests = chunk_guests['guests']
                all_guests.extend(chunk_guests)
                total_inp += response.usage.input_tokens
                total_out += response.usage.output_tokens

            # Inserisci nel DB
            added = 0
            skipped = 0
            for gd in all_guests:
                cognome = (gd.get('cognome') or '').strip()
                if not cognome:
                    skipped += 1
                    continue
                g = Guest(
                    cognome=cognome,
                    nome=(gd.get('nome') or '').strip(),
                    email=gd.get('email'),
                    telefono=gd.get('telefono'),
                    sede_lavoro=gd.get('sede_lavoro'),
                    presenza_8=_parse_bool(gd.get('presenza_8')),
                    presenza_9=_parse_bool(gd.get('presenza_9')),
                    presenza_10=_parse_bool(gd.get('presenza_10')),
                    presenza_11=_parse_bool(gd.get('presenza_11')),
                    volo_arrivo=gd.get('volo_arrivo'),
                    volo_partenza=gd.get('volo_partenza'),
                    aeroporto_partenza=gd.get('aeroporto_partenza'),
                    aeroporto_arrivo=gd.get('aeroporto_arrivo'),
                    pickup_bus_andata=gd.get('pickup_bus_andata'),
                    pickup_bus_ritorno=gd.get('pickup_bus_ritorno'),
                    parcheggio_linate=_parse_bool(gd.get('parcheggio_linate')),
                    parcheggio_hotel=_parse_bool(gd.get('parcheggio_hotel')),
                    divide_stanza_con=gd.get('divide_stanza_con'),
                    restrizioni_alimentari=gd.get('restrizioni_alimentari'),
                    tipo_camera=gd.get('tipo_camera'),
                    note_form=gd.get('note_form'),
                    note=gd.get('note'),
                    source='xlsx',
                )
                db.session.add(g)
                added += 1

            db.session.commit()
            cost = (total_inp * 0.80 + total_out * 4.00) / 1_000_000

            try:
                os.remove(tmp_path)
            except OSError:
                pass

            return jsonify(ok=True, added=added, skipped=skipped,
                           usage={'input': total_inp, 'output': total_out,
                                  'cost_eur': round(cost * 0.92, 4)})

        # ── Fallback: mapping diretto senza LLM (nessuna trasformazione) ──
        col_map = {}
        for idx_str, info in mapping.items():
            campo = info.get('campo', 'IGNORA') if isinstance(info, dict) else info
            if campo != 'IGNORA':
                col_map[campo] = int(idx_str)

        if 'cognome' not in col_map and 'nome_completo' not in col_map:
            return jsonify(ok=False, error='Nessuna colonna mappata a cognome o nome completo'), 400

        added = 0
        skipped = 0

        for row in rows:
            if 'nome_completo' in col_map:
                full = row[col_map['nome_completo']].strip() if col_map['nome_completo'] < len(row) else ''
                if not full:
                    skipped += 1
                    continue
                formato = None
                for idx_str, info in mapping.items():
                    if isinstance(info, dict) and info.get('campo') == 'nome_completo':
                        formato = info.get('formato', 'nome cognome')
                        break
                parts = full.split(None, 1)
                if formato and 'cognome' in formato.split()[0].lower():
                    cognome = parts[0] if parts else full
                    nome = parts[1] if len(parts) > 1 else ''
                else:
                    nome = parts[0] if parts else ''
                    cognome = parts[1] if len(parts) > 1 else full
            else:
                cognome = row[col_map['cognome']].strip() if col_map.get('cognome') is not None and col_map['cognome'] < len(row) else ''
                if not cognome:
                    skipped += 1
                    continue
                nome = row[col_map['nome']].strip() if col_map.get('nome') is not None and col_map['nome'] < len(row) else ''

            def get_val(campo):
                idx = col_map.get(campo)
                if idx is not None and idx < len(row):
                    v = row[idx].strip()
                    return v if v else None
                return None

            g = Guest(
                cognome=cognome,
                nome=nome,
                email=get_val('email'),
                telefono=get_val('telefono'),
                sede_lavoro=get_val('sede_lavoro'),
                presenza_8=_parse_bool(get_val('presenza_8')),
                presenza_9=_parse_bool(get_val('presenza_9')),
                presenza_10=_parse_bool(get_val('presenza_10')),
                presenza_11=_parse_bool(get_val('presenza_11')),
                volo_arrivo=get_val('volo_arrivo'),
                volo_partenza=get_val('volo_partenza'),
                aeroporto_partenza=get_val('aeroporto_partenza'),
                aeroporto_arrivo=get_val('aeroporto_arrivo'),
                pickup_bus_andata=get_val('pickup_bus_andata'),
                pickup_bus_ritorno=get_val('pickup_bus_ritorno'),
                parcheggio_linate=_parse_bool(get_val('parcheggio_linate')),
                parcheggio_hotel=_parse_bool(get_val('parcheggio_hotel')),
                divide_stanza_con=get_val('divide_stanza_con'),
                restrizioni_alimentari=get_val('restrizioni_alimentari'),
                tipo_camera=get_val('tipo_camera'),
                note_form=get_val('note_form'),
                note=get_val('note'),
                source='xlsx',
            )
            db.session.add(g)
            added += 1

        db.session.commit()

        try:
            os.remove(tmp_path)
        except OSError:
            pass

        return jsonify(ok=True, added=added, skipped=skipped)

    # ── STANZE PER GIORNO ───────────────────────────────────────────────────

    @app.get('/api/stanze/<int:giorno>')
    def stanze_giorno(giorno):
        """Calcola stanze necessarie per un giorno (8, 9, 10, 11)."""
        if giorno not in (8, 9, 10, 11):
            return jsonify(ok=False, error='Giorno non valido'), 400

        campo = f'presenza_{giorno}'
        presenti = Guest.query.filter(getattr(Guest, campo) == True).order_by(
            Guest.cognome, Guest.nome).all()

        # Raggruppa per stanze: chi condivide conta come 1 stanza
        stanze = []       # lista di liste di nomi
        assegnati = set() # id già assegnati a una stanza

        for g in presenti:
            if g.id in assegnati:
                continue

            stanza = [g]
            assegnati.add(g.id)

            if g.divide_stanza_con and g.divide_stanza_con.strip():
                # Cerca i compagni di stanza tra i presenti
                compagni_nomi = [n.strip().lower() for n in g.divide_stanza_con.split(',')]
                for p in presenti:
                    if p.id in assegnati:
                        continue
                    nome_completo = f'{p.nome} {p.cognome}'.lower()
                    cognome_lower = p.cognome.lower()
                    nome_lower = p.nome.lower()
                    # Match flessibile: nome completo, solo cognome, o solo nome
                    for cn in compagni_nomi:
                        if (cn in nome_completo or cn in cognome_lower
                                or cn in nome_lower or cognome_lower in cn
                                or nome_lower in cn):
                            stanza.append(p)
                            assegnati.add(p.id)
                            break

            stanze.append(stanza)

        # Serializza
        result = []
        for stanza in stanze:
            result.append({
                'ospiti': [
                    {'id': g.id, 'cognome': g.cognome, 'nome': g.nome,
                     'tipo_camera': g.tipo_camera or '',
                     'divide_stanza_con': g.divide_stanza_con or ''}
                    for g in stanza
                ],
                'tipo_camera': stanza[0].tipo_camera or '',
            })

        return jsonify(
            ok=True,
            giorno=giorno,
            totale_presenti=len(presenti),
            totale_stanze=len(stanze),
            stanze=result,
        )

    # ── VOLI RAGGRUPPATI ────────────────────────────────────────────────────

    @app.get('/api/voli/<tipo>')
    def voli_raggruppati(tipo):
        """Raggruppa ospiti per volo. tipo = 'andata' o 'ritorno'."""
        if tipo not in ('andata', 'ritorno'):
            return jsonify(ok=False, error='Tipo non valido (andata/ritorno)'), 400

        campo = Guest.volo_arrivo if tipo == 'andata' else Guest.volo_partenza
        guests = Guest.query.filter(campo.isnot(None), campo != '').order_by(
            campo, Guest.cognome, Guest.nome).all()

        # Raggruppa per codice volo
        gruppi = {}
        for g in guests:
            volo = (g.volo_arrivo if tipo == 'andata' else g.volo_partenza).strip()
            if not volo:
                continue
            if volo not in gruppi:
                gruppi[volo] = []
            gruppi[volo].append({
                'id': g.id,
                'cognome': g.cognome,
                'nome': g.nome,
                'sede_lavoro': g.sede_lavoro or '',
                'aeroporto': (g.aeroporto_partenza if tipo == 'andata' else g.aeroporto_arrivo) or '',
            })

        # Ordina per codice volo
        result = []
        for volo in sorted(gruppi.keys()):
            result.append({
                'volo': volo,
                'passeggeri': gruppi[volo],
                'totale': len(gruppi[volo]),
            })

        senza_volo = Guest.query.filter(
            (campo.is_(None)) | (campo == '')
        ).count()

        return jsonify(
            ok=True,
            tipo=tipo,
            gruppi=result,
            totale_con_volo=len(guests),
            totale_senza_volo=senza_volo,
            totale_voli=len(result),
        )

    # ── ASSEGNAZIONE CAMERE ─────────────────────────────────────────────────

    @app.get('/api/camere/<int:notte>')
    def camere_disponibilita(notte):
        """Mostra disponibilità camere vs assegnazioni per una notte."""
        if notte not in (8, 9, 10, 11):
            return jsonify(ok=False, error='Notte non valida'), 400

        contratti = RoomContract.query.filter_by(notte=notte).order_by(
            RoomContract.tariffa_netta).all()

        campo = f'presenza_{notte}'
        presenti = Guest.query.filter(getattr(Guest, campo) == True).order_by(
            Guest.cognome, Guest.nome).all()

        # Calcola stanze necessarie (come endpoint stanze)
        assegnati_ids = set()
        stanze_necessarie = []
        for g in presenti:
            if g.id in assegnati_ids:
                continue
            stanza = [g]
            assegnati_ids.add(g.id)
            if g.divide_stanza_con and g.divide_stanza_con.strip():
                compagni = [n.strip().lower() for n in g.divide_stanza_con.split(',')]
                for p in presenti:
                    if p.id in assegnati_ids:
                        continue
                    nc = f'{p.nome} {p.cognome}'.lower()
                    cl = p.cognome.lower()
                    nl = p.nome.lower()
                    for cn in compagni:
                        if cn in nc or cn in cl or cn in nl or cl in cn or nl in cn:
                            stanza.append(p)
                            assegnati_ids.add(p.id)
                            break
            stanze_necessarie.append(stanza)

        # Conta assegnazioni per tipo
        assegnazioni_per_tipo = {}
        non_assegnati = []
        for stanza in stanze_necessarie:
            camera = stanza[0].camera_assegnata
            if camera:
                assegnazioni_per_tipo[camera] = assegnazioni_per_tipo.get(camera, 0) + 1
            else:
                non_assegnati.append(stanza)

        result_contratti = []
        for c in contratti:
            usate = assegnazioni_per_tipo.get(c.tipo, 0)
            result_contratti.append({
                'id': c.id,
                'tipo': c.tipo,
                'disponibili': c.disponibili,
                'assegnate': usate,
                'libere': c.disponibili - usate,
                'tariffa_netta': c.tariffa_netta,
                'tariffa_lorda': c.tariffa_lorda,
            })

        result_non_assegnati = []
        for stanza in non_assegnati:
            result_non_assegnati.append({
                'ospiti': [{'id': g.id, 'cognome': g.cognome, 'nome': g.nome,
                            'tipo_camera': g.tipo_camera or ''}
                           for g in stanza],
            })

        return jsonify(
            ok=True,
            notte=notte,
            contratti=result_contratti,
            totale_stanze_necessarie=len(stanze_necessarie),
            totale_assegnate=len(stanze_necessarie) - len(non_assegnati),
            totale_non_assegnate=len(non_assegnati),
            non_assegnati=result_non_assegnati,
        )

    @app.post('/api/camere/assegna')
    def assegna_camera():
        """Assegna manualmente un tipo camera a un ospite (e al suo compagno di stanza)."""
        data = request.get_json()
        guest_id = data.get('guest_id')
        tipo_camera = data.get('tipo_camera')

        if not guest_id or not tipo_camera:
            return jsonify(ok=False, error='guest_id e tipo_camera obbligatori'), 400

        g = Guest.query.get_or_404(guest_id)
        g.camera_assegnata = tipo_camera
        g.updated_at = datetime.utcnow()

        # Assegna anche ai compagni di stanza
        assegnati = [g.id]
        if g.divide_stanza_con and g.divide_stanza_con.strip():
            compagni = [n.strip().lower() for n in g.divide_stanza_con.split(',')]
            tutti = Guest.query.all()
            for p in tutti:
                if p.id == g.id:
                    continue
                nc = f'{p.nome} {p.cognome}'.lower()
                cl = p.cognome.lower()
                nl = p.nome.lower()
                for cn in compagni:
                    if cn in nc or cn in cl or cn in nl or cl in cn or nl in cn:
                        p.camera_assegnata = tipo_camera
                        p.updated_at = datetime.utcnow()
                        assegnati.append(p.id)
                        break

        db.session.commit()
        return jsonify(ok=True, assegnati=assegnati)

    @app.post('/api/camere/auto-assegna/<int:notte>')
    def auto_assegna(notte):
        """Assegna automaticamente le camere per una notte, dal tipo più economico."""
        if notte not in (8, 9, 10, 11):
            return jsonify(ok=False, error='Notte non valida'), 400

        contratti = RoomContract.query.filter_by(notte=notte).order_by(
            RoomContract.tariffa_netta).all()

        campo = f'presenza_{notte}'
        presenti = Guest.query.filter(getattr(Guest, campo) == True).order_by(
            Guest.cognome, Guest.nome).all()

        # Calcola stanze
        assegnati_ids = set()
        stanze = []
        for g in presenti:
            if g.id in assegnati_ids:
                continue
            stanza = [g]
            assegnati_ids.add(g.id)
            if g.divide_stanza_con and g.divide_stanza_con.strip():
                compagni = [n.strip().lower() for n in g.divide_stanza_con.split(',')]
                for p in presenti:
                    if p.id in assegnati_ids:
                        continue
                    nc = f'{p.nome} {p.cognome}'.lower()
                    cl = p.cognome.lower()
                    nl = p.nome.lower()
                    for cn in compagni:
                        if cn in nc or cn in cl or cn in nl or cl in cn or nl in cn:
                            stanza.append(p)
                            assegnati_ids.add(p.id)
                            break
            stanze.append(stanza)

        # Filtra solo stanze non ancora assegnate
        stanze_da_assegnare = [s for s in stanze if not s[0].camera_assegnata]

        # Assegna partendo dal tipo più economico
        assegnate = 0
        overflow = 0
        for contratto in contratti:
            # Quante già usate di questo tipo?
            gia_usate = sum(1 for s in stanze if s[0].camera_assegnata == contratto.tipo)
            libere = contratto.disponibili - gia_usate

            while libere > 0 and stanze_da_assegnare:
                stanza = stanze_da_assegnare.pop(0)
                for g in stanza:
                    g.camera_assegnata = contratto.tipo
                    g.updated_at = datetime.utcnow()
                libere -= 1
                assegnate += 1

        overflow = len(stanze_da_assegnare)
        db.session.commit()

        return jsonify(ok=True, assegnate=assegnate, overflow=overflow,
                       messaggio=f'{assegnate} stanze assegnate' +
                       (f', {overflow} senza camera disponibile' if overflow else ''))

    @app.post('/api/camere/reset/<int:notte>')
    def reset_assegnazioni(notte):
        """Rimuove tutte le assegnazioni camera per una notte."""
        if notte not in (8, 9, 10, 11):
            return jsonify(ok=False, error='Notte non valida'), 400

        campo = f'presenza_{notte}'
        presenti = Guest.query.filter(getattr(Guest, campo) == True).all()
        for g in presenti:
            g.camera_assegnata = None
            g.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(ok=True)

    # ── EXPORT XLSX ──────────────────────────────────────────────────────────

    @app.get('/api/export')
    def export_xlsx():
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        guests = Guest.query.order_by(Guest.cognome, Guest.nome).all()
        wb = Workbook()

        header_font = Font(bold=True, color='FFFFFF', size=11)
        header_fill = PatternFill('solid', fgColor='795548')
        header_fill2 = PatternFill('solid', fgColor='6D4C41')
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin'),
        )

        def write_sheet(ws, headers, row_fn, fill=header_fill):
            for c, h in enumerate(headers, 1):
                cell = ws.cell(row=1, column=c, value=h)
                cell.font = header_font
                cell.fill = fill
                cell.alignment = Alignment(horizontal='center')
                cell.border = thin_border
            for r, g in enumerate(guests, 2):
                for c, v in enumerate(row_fn(g), 1):
                    cell = ws.cell(row=r, column=c, value=v if v is not None else '')
                    cell.border = thin_border
            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        def bool_label(v):
            return 'Sì' if v else 'No'

        # ── Sheet 1: Anagrafica completa ──────────────────────────────────────
        ws = wb.active
        ws.title = 'Anagrafica'
        write_sheet(ws,
            ['Cognome', 'Nome', 'Email', 'Telefono', 'Sede Lavoro',
             '8 Ott', '9 Ott', '10 Ott', '11 Ott',
             'Tipo Camera', 'Divide stanza con',
             'Parcheggio Linate', 'Parcheggio Hotel',
             'Restrizioni Alimentari', 'Note Form', 'Note'],
            lambda g: [g.cognome, g.nome, g.email, g.telefono, g.sede_lavoro,
                       bool_label(g.presenza_8), bool_label(g.presenza_9),
                       bool_label(g.presenza_10), bool_label(g.presenza_11),
                       g.tipo_camera, g.divide_stanza_con,
                       bool_label(g.parcheggio_linate), bool_label(g.parcheggio_hotel),
                       g.restrizioni_alimentari, g.note_form, g.note])

        # ── Sheet 2: Voli e Trasporti ─────────────────────────────────────────
        ws2 = wb.create_sheet('Voli e Trasporti')
        write_sheet(ws2,
            ['Cognome', 'Nome', 'Sede Lavoro',
             'Aeroporto Partenza', 'Volo Andata',
             'Aeroporto Arrivo', 'Volo Ritorno',
             'Pickup Bus Andata', 'Pickup Bus Ritorno'],
            lambda g: [g.cognome, g.nome, g.sede_lavoro,
                       g.aeroporto_partenza, g.volo_arrivo,
                       g.aeroporto_arrivo, g.volo_partenza,
                       g.pickup_bus_andata, g.pickup_bus_ritorno],
            fill=header_fill2)

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)

        today = datetime.now().strftime('%Y-%m-%d')
        return send_file(buf, as_attachment=True,
                         download_name=f'rooming_flight_{today}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── EMAIL PARSING (LLM) ─────────────────────────────────────────────────

    @app.post('/api/parse-email')
    def parse_email():
        import anthropic

        data = request.get_json()
        text = (data.get('text') or '').strip()
        if not text:
            return jsonify(ok=False, error='Testo vuoto'), 400

        # Raccogli ospiti esistenti per contesto
        guests = Guest.query.order_by(Guest.cognome).all()
        guest_list = '\n'.join(
            f'- [id={g.id}] {g.cognome} {g.nome} (camera: {g.tipo_camera or "n/a"}, '
            f'arrivo: {g.volo_arrivo or "n/a"}, partenza: {g.volo_partenza or "n/a"}, '
            f'email: {g.email or "n/a"})'
            for g in guests
        ) or '(nessun ospite ancora registrato)'

        system_prompt = f"""Sei un assistente che estrae dati di rooming e voli da email/messaggi.

Ospiti attualmente in lista:
{guest_list}

Estrai TUTTE le informazioni su ospiti menzionati nel testo. Per ogni persona, determina:
- cognome (MAIUSCOLO)
- nome
- email, telefono
- sede_lavoro (città/sede di lavoro)
- volo_arrivo (codice volo + orario), volo_partenza (codice volo + orario)
- aeroporto_partenza, aeroporto_arrivo
- pickup_bus_andata, pickup_bus_ritorno (orario pickup bus)
- tipo_camera (singola, doppia, twin, suite, etc.)
- presenza_8, presenza_9, presenza_10, presenza_11 (true/false, giorni 8-11 ottobre)
- parcheggio_linate, parcheggio_hotel (true/false)
- divide_stanza_con (con chi condivide la stanza)
- restrizioni_alimentari
- azione: "update" se la persona esiste già in lista, "add" se è nuova

Se un campo non è menzionato nel testo, usa null.
Se la persona esiste già, includi SOLO i campi che vanno aggiornati (gli altri null).

Rispondi SOLO con JSON valido, niente markdown:
{{
  "guests": [
    {{
      "cognome": "ROSSI",
      "nome": "Mario",
      "email": null,
      "telefono": null,
      "sede_lavoro": null,
      "volo_arrivo": "AZ1234 08:25",
      "volo_partenza": null,
      "tipo_camera": "doppia",
      "presenza_8": true,
      "presenza_9": true,
      "presenza_10": null,
      "presenza_11": null,
      "parcheggio_linate": null,
      "parcheggio_hotel": null,
      "divide_stanza_con": null,
      "restrizioni_alimentari": null,
      "azione": "add",
      "match_id": null,
      "nota": "breve spiegazione di cosa hai interpretato"
    }}
  ],
  "summary": "riassunto di cosa dice l'email"
}}

Per "azione": "update", valorizza "match_id" con l'ID dell'ospite corrispondente.
"""

        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            return jsonify(ok=False, error='ANTHROPIC_API_KEY non configurata'), 500

        client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=2048,
                system=system_prompt,
                messages=[{'role': 'user', 'content': text}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith('```'):
                raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
                if raw.endswith('```'):
                    raw = raw[:-3]
                raw = raw.strip()

            parsed = json.loads(raw)

            # Costo (Haiku 4.5: $0.80/MTok in, $4.00/MTok out)
            inp = response.usage.input_tokens
            out = response.usage.output_tokens
            cost = (inp * 0.80 + out * 4.00) / 1_000_000

            # Se match_id non fornito dal LLM, prova fuzzy match
            for g in parsed.get('guests', []):
                if g.get('azione') == 'update' and not g.get('match_id'):
                    match = Guest.query.filter(
                        db.func.upper(Guest.cognome) == (g.get('cognome') or '').upper()
                    ).first()
                    if match:
                        g['match_id'] = match.id
                        g['match_nome'] = match.nome_completo

            # Per ogni update, includi i dati attuali per confronto
            compare_fields = ('cognome', 'nome', 'email', 'telefono', 'sede_lavoro',
                              'volo_arrivo', 'volo_partenza',
                              'aeroporto_partenza', 'aeroporto_arrivo',
                              'pickup_bus_andata', 'pickup_bus_ritorno',
                              'divide_stanza_con', 'restrizioni_alimentari',
                              'tipo_camera', 'note_form',
                              'presenza_8', 'presenza_9', 'presenza_10', 'presenza_11',
                              'parcheggio_linate', 'parcheggio_hotel')
            for g in parsed.get('guests', []):
                if g.get('azione') == 'update' and g.get('match_id'):
                    existing = Guest.query.get(g['match_id'])
                    if existing:
                        g['current_data'] = {f: getattr(existing, f) for f in compare_fields}

            # Salva il messaggio originale nel log (anche se non verrà applicato)
            email_log = EmailLog(testo=text, summary=parsed.get('summary'))
            db.session.add(email_log)
            db.session.commit()

            return jsonify(ok=True, parsed=parsed, email_log_id=email_log.id,
                           usage={'input': inp, 'output': out, 'cost_eur': round(cost * 0.92, 4)})

        except json.JSONDecodeError:
            return jsonify(ok=False, error=f'Risposta LLM non valida: {raw[:300]}'), 500
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    @app.post('/api/apply-parsed')
    def apply_parsed():
        """Applica le azioni estratte dal parsing email."""
        data = request.get_json()
        guests_data = data.get('guests', [])
        email_log_id = data.get('email_log_id')

        results = []
        for gd in guests_data:
            azione = gd.get('azione', 'add')
            cognome = (gd.get('cognome') or '').strip()
            nome = (gd.get('nome') or '').strip()

            str_fields = ('email', 'telefono', 'sede_lavoro',
                          'volo_arrivo', 'volo_partenza',
                          'aeroporto_partenza', 'aeroporto_arrivo',
                          'pickup_bus_andata', 'pickup_bus_ritorno',
                          'divide_stanza_con', 'restrizioni_alimentari',
                          'tipo_camera', 'note_form')
            bool_fields = ('presenza_8', 'presenza_9', 'presenza_10', 'presenza_11',
                           'parcheggio_linate', 'parcheggio_hotel')

            if azione == 'update' and gd.get('match_id'):
                g = Guest.query.get(gd['match_id'])
                if not g:
                    results.append({'cognome': cognome, 'ok': False, 'error': 'Non trovato'})
                    continue
                if cognome:
                    g.cognome = cognome
                if nome:
                    g.nome = nome
                for f in str_fields:
                    if gd.get(f) is not None:
                        setattr(g, f, gd[f])
                for f in bool_fields:
                    if gd.get(f) is not None:
                        setattr(g, f, _parse_bool(gd[f]))
                g.updated_at = datetime.utcnow()
                if email_log_id:
                    g.email_log_id = email_log_id
                results.append({'cognome': cognome, 'ok': True, 'action': 'updated', 'id': g.id})
            else:
                kwargs = dict(cognome=cognome, nome=nome, source='email',
                              note=gd.get('nota'),
                              email_log_id=email_log_id)
                for f in str_fields:
                    kwargs[f] = gd.get(f)
                for f in bool_fields:
                    kwargs[f] = _parse_bool(gd.get(f))
                g = Guest(**kwargs)
                db.session.add(g)
                db.session.flush()
                results.append({'cognome': cognome, 'ok': True, 'action': 'added', 'id': g.id})

        db.session.commit()
        return jsonify(ok=True, results=results)

    # ── EMAIL LOG ─────────────────────────────────────────────────────────

    @app.get('/api/email-logs')
    def list_email_logs():
        logs = EmailLog.query.order_by(EmailLog.created_at.desc()).all()
        return jsonify([{
            'id': l.id,
            'summary': l.summary,
            'testo': l.testo,
            'created_at': l.created_at.isoformat(),
            'guests': [{'id': g.id, 'nome_completo': g.nome_completo}
                        for g in Guest.query.filter_by(email_log_id=l.id).all()]
        } for l in logs])

    @app.get('/api/email-log/<int:log_id>')
    def get_email_log(log_id):
        log = EmailLog.query.get_or_404(log_id)
        return jsonify(id=log.id, testo=log.testo, summary=log.summary,
                       created_at=log.created_at.isoformat())

    # ── DELETE ALL ───────────────────────────────────────────────────────────

    @app.delete('/api/guests')
    def delete_all():
        Guest.query.delete()
        db.session.commit()
        return jsonify(ok=True)

    # ══════════════════════════════════════════════════════════════════════════
    # ██  PARTIVIA — Preventivi Hotel                                       ██
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/partivia')
    def partivia():
        import re

        quotes = (PartiviaQuote.query
                  .order_by(PartiviaQuote.city, PartiviaQuote.hotel_name)
                  .all())

        # ── Normalizzazione tipo camera per pivot ──
        def normalize_room_type(rt):
            rt_l = rt.lower().strip()
            if 'suite' in rt_l and 'junior' not in rt_l:
                return 'Suite'
            if 'junior' in rt_l:
                return 'Junior Suite'
            if 'singol' in rt_l or 'single' in rt_l:
                return 'Singola'
            if 'superior' in rt_l:
                return 'Superior'
            if 'deluxe' in rt_l:
                return 'Deluxe'
            if any(k in rt_l for k in ('doppi', 'double', 'twin', 'dbl')):
                return 'Doppia/Twin'
            if 'triple' in rt_l or 'tripl' in rt_l:
                return 'Tripla'
            return rt.strip()

        # ── Normalizzazione tipo pasto per pivot ──
        def normalize_meal_type(mt):
            mt_l = mt.lower().strip()
            if 'coffee' in mt_l or 'break' in mt_l:
                return 'Coffee Break'
            if 'cocktail' in mt_l or 'welcome' in mt_l or 'aperitivo' in mt_l:
                return 'Cocktail'
            if 'gala' in mt_l:
                return 'Gala Dinner'
            if 'cena' in mt_l or 'dinner' in mt_l:
                return 'Cena'
            if 'pranzo' in mt_l or 'lunch' in mt_l or 'buffet' in mt_l:
                return 'Pranzo'
            if 'colazione' in mt_l or 'breakfast' in mt_l:
                return 'Colazione'
            if 'ddr' in mt_l or 'delegate' in mt_l:
                return 'DDR'
            return mt.strip()

        # ── Estrai numero da stringa prezzo ──
        def parse_price(s):
            if not s:
                return None
            m = re.search(r'[\d.,]+', s.replace('.', '').replace(',', '.'))
            return float(m.group()) if m else None

        # ── Dati aggregati per le tab ──
        ROOM_COLS = ['Singola', 'Doppia/Twin', 'Superior', 'Deluxe',
                     'Junior Suite', 'Suite']
        MEAL_COLS = ['Colazione', 'Coffee Break', 'Pranzo', 'Cena',
                     'Cocktail', 'Gala Dinner', 'DDR']

        room_pivot = []  # lista di dict per ogni quote
        fb_pivot = []
        for q in quotes:
            # Room pivot
            rates_map = {}
            for rr in q.room_rates:
                norm = normalize_room_type(rr.room_type)
                if norm not in rates_map:
                    rates_map[norm] = rr.rate_per_night or ''
            room_pivot.append({
                'id': q.id,
                'hotel': q.hotel_name,
                'city': q.city,
                'stars': q.stars,
                'rooms': q.rooms_available or '',
                'rates': {col: rates_map.get(col, '') for col in ROOM_COLS},
                'price_val': parse_price(rates_map.get('Doppia/Twin')
                                         or rates_map.get('Singola')),
            })

            # F&B pivot
            fb_map = {}
            for fb in q.fb_options:
                norm = normalize_meal_type(fb.meal_type)
                if norm not in fb_map:
                    fb_map[norm] = fb.price_per_person or ''
            fb_pivot.append({
                'id': q.id,
                'hotel': q.hotel_name,
                'city': q.city,
                'meals': {col: fb_map.get(col, '') for col in MEAL_COLS},
            })

        # ── Raggruppa per hotel (per Overview) ──
        hotels_grouped = {}  # key = hotel_name_lower → list of quotes
        for q in quotes:
            key = q.hotel_name.lower().strip()
            hotels_grouped.setdefault(key, []).append(q)

        # Per ogni gruppo, scegli il "best" (più dati) e tieni le versioni
        hotels = []  # lista di dict con best + versions
        for key, group in hotels_grouped.items():
            # Ordina per completezza: più room_rates + meeting_rooms + fb_options
            scored = sorted(group, key=lambda q: (
                len(q.room_rates) + len(q.meeting_rooms) + len(q.fb_options)
            ), reverse=True)
            best = scored[0]
            hotels.append({
                'best': best,
                'versions': group,
                'count': len(group),
            })

        # Ordina hotels per città + nome
        hotels.sort(key=lambda h: (h['best'].city, h['best'].hotel_name))

        # Stats
        cities = {}
        stars_count = {}
        status_count = {}
        for q in quotes:
            cities[q.city] = cities.get(q.city, 0) + 1
            s = q.stars or 0
            stars_count[s] = stars_count.get(s, 0) + 1
            status_count[q.quote_status] = status_count.get(q.quote_status, 0) + 1

        return render_template('partivia.html',
                               quotes=quotes,
                               hotels=hotels,
                               room_pivot=room_pivot,
                               room_cols=ROOM_COLS,
                               fb_pivot=fb_pivot,
                               meal_cols=MEAL_COLS,
                               stats_cities=cities,
                               stats_stars=stars_count,
                               stats_status=status_count)

    # ── Parse email preventivo ────────────────────────────────────────────

    @app.post('/api/partivia/parse-email')
    def partivia_parse_email():
        import anthropic

        data = request.get_json()
        text = (data.get('text') or '').strip()
        if not text:
            return jsonify(ok=False, error='Testo vuoto'), 400

        # Contesto: preventivi già in DB
        existing = PartiviaQuote.query.order_by(PartiviaQuote.city).all()
        existing_list = '\n'.join(
            f'- [id={q.id}] {q.hotel_name} ({q.city}, {q.stars or "?"}★) '
            f'— stato: {q.quote_status}, date: {q.dates_proposed or "n/a"}'
            for q in existing
        ) or '(nessun preventivo ancora registrato)'

        system_prompt = f"""Sei un assistente che estrae dati di preventivi hotel da email.
L'evento è "N!Partivia" — un viaggio incentive aziendale in Spagna.
Possibili destinazioni: Barcellona, Madrid, Siviglia, Valencia.

Preventivi già registrati:
{existing_list}

Analizza l'email e estrai TUTTI i preventivi/offerte hotel presenti.
Per ogni preventivo, estrai:
- hotel_name (nome hotel)
- city (Barcellona, Madrid, Siviglia o Valencia — normalizza sempre in italiano)
- stars (stelle, intero 1-5 o null)
- contact_name, contact_email (contatto hotel)
- dates_proposed (date proposte, es. "10-13 ottobre 2026")
- rooms_available (camere disponibili)
- min_rooms_required (minimo camere richieste)
- room_rates: lista di oggetti con room_type, rate_per_night (con €), breakfast_included (sì/no/non specificato), notes
- meeting_rooms: lista con name, capacity, rate, notes
- fb_options: lista con meal_type (colazione/pranzo/cena/coffee break/gala dinner), price_per_person, menu_description
- cancellation_policy, payment_terms, validity_date, commission
- total_estimate (stima totale se presente)
- included_services (lista servizi inclusi come WiFi, parcheggio, etc.)
- notes (condizioni speciali, upgrade offerti)
- raw_summary (riassunto del contenuto in 2-3 frasi)
- is_update: true se aggiorna un preventivo già in lista (con match_id), false se è nuovo
- match_id: ID del preventivo esistente se è un aggiornamento, null se nuovo

Se il messaggio NON contiene preventivi (es. semplice follow-up), imposta is_quote=false.

Rispondi SOLO con JSON valido (niente markdown):
{{
  "quotes": [
    {{
      "hotel_name": "Hotel Example",
      "city": "Barcellona",
      "stars": 4,
      "contact_name": "Mario Rossi",
      "contact_email": "mario@hotel.com",
      "dates_proposed": "10-13 ottobre 2026",
      "rooms_available": "80",
      "min_rooms_required": null,
      "room_rates": [
        {{"room_type": "Doppia", "rate_per_night": "€ 180", "breakfast_included": "sì", "notes": null}}
      ],
      "meeting_rooms": [
        {{"name": "Sala Grande", "capacity": "200 pax teatro", "rate": "€ 2.000/giorno", "notes": "AV incluso"}}
      ],
      "fb_options": [
        {{"meal_type": "Cena", "price_per_person": "€ 55/pax", "menu_description": "Menu 3 portate"}}
      ],
      "cancellation_policy": "Cancellazione gratuita entro 30gg",
      "payment_terms": "30% alla conferma",
      "validity_date": "30/09/2026",
      "commission": "10%",
      "total_estimate": "€ 45.000",
      "included_services": ["WiFi", "Parcheggio", "Palestra"],
      "notes": "Upgrade camera su richiesta",
      "raw_summary": "Hotel Example propone 80 camere doppie a €180/notte...",
      "is_update": false,
      "match_id": null
    }}
  ],
  "is_quote": true,
  "message_type": "preventivo",
  "summary": "Ricevuto preventivo da Hotel Example per Barcellona..."
}}"""

        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            return jsonify(ok=False, error='ANTHROPIC_API_KEY non configurata'), 500

        client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=4096,
                system=system_prompt,
                messages=[{'role': 'user', 'content': text}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith('```'):
                raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
                if raw.endswith('```'):
                    raw = raw[:-3]
                raw = raw.strip()

            parsed = json.loads(raw)

            # Costo (Haiku 4.5)
            inp = response.usage.input_tokens
            out = response.usage.output_tokens
            cost = (inp * 0.80 + out * 4.00) / 1_000_000

            # Salva log
            email_log = EmailLog(testo=text, summary=parsed.get('summary'))
            db.session.add(email_log)
            db.session.commit()

            return jsonify(ok=True, parsed=parsed, email_log_id=email_log.id,
                           usage={'input': inp, 'output': out,
                                  'cost_eur': round(cost * 0.92, 4)})

        except json.JSONDecodeError:
            return jsonify(ok=False, error=f'Risposta LLM non valida: {raw[:300]}'), 500
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    # ── Applica preventivi estratti ───────────────────────────────────────

    @app.post('/api/partivia/apply')
    def partivia_apply():
        data = request.get_json()
        quotes_data = data.get('quotes', [])
        email_log_id = data.get('email_log_id')

        results = []
        for qd in quotes_data:
            is_update = qd.get('is_update', False)
            match_id = qd.get('match_id')

            if is_update and match_id:
                q = PartiviaQuote.query.get(match_id)
                if not q:
                    results.append({'hotel': qd.get('hotel_name'),
                                    'ok': False, 'error': 'Non trovato'})
                    continue
                # Aggiorna campi top-level
                for field in ('hotel_name', 'city', 'stars', 'contact_name',
                              'contact_email', 'dates_proposed', 'rooms_available',
                              'min_rooms_required', 'cancellation_policy',
                              'payment_terms', 'validity_date', 'commission',
                              'total_estimate', 'notes', 'raw_summary'):
                    if qd.get(field) is not None:
                        setattr(q, field, qd[field])
                if qd.get('included_services'):
                    q.included_services = ', '.join(qd['included_services'])
                q.updated_at = datetime.utcnow()
                if email_log_id:
                    q.email_log_id = email_log_id

                # Sostituisci sotto-tabelle se fornite
                if qd.get('room_rates'):
                    PartiviaRoomRate.query.filter_by(quote_id=q.id).delete()
                    for rr in qd['room_rates']:
                        db.session.add(PartiviaRoomRate(
                            quote_id=q.id, room_type=rr.get('room_type', ''),
                            rate_per_night=rr.get('rate_per_night'),
                            breakfast_included=rr.get('breakfast_included'),
                            notes=rr.get('notes')))
                if qd.get('meeting_rooms'):
                    PartiviaMeetingRoom.query.filter_by(quote_id=q.id).delete()
                    for mr in qd['meeting_rooms']:
                        db.session.add(PartiviaMeetingRoom(
                            quote_id=q.id, name=mr.get('name', ''),
                            capacity=mr.get('capacity'),
                            rate=mr.get('rate'), notes=mr.get('notes')))
                if qd.get('fb_options'):
                    PartiviaFBOption.query.filter_by(quote_id=q.id).delete()
                    for fb in qd['fb_options']:
                        db.session.add(PartiviaFBOption(
                            quote_id=q.id, meal_type=fb.get('meal_type', ''),
                            price_per_person=fb.get('price_per_person'),
                            menu_description=fb.get('menu_description')))

                db.session.flush()
                results.append({'hotel': q.hotel_name, 'ok': True,
                                'action': 'updated', 'id': q.id})
            else:
                # Nuovo preventivo
                q = PartiviaQuote(
                    hotel_name=qd.get('hotel_name', ''),
                    city=qd.get('city', ''),
                    stars=qd.get('stars'),
                    contact_name=qd.get('contact_name'),
                    contact_email=qd.get('contact_email'),
                    dates_proposed=qd.get('dates_proposed'),
                    rooms_available=qd.get('rooms_available'),
                    min_rooms_required=qd.get('min_rooms_required'),
                    cancellation_policy=qd.get('cancellation_policy'),
                    payment_terms=qd.get('payment_terms'),
                    validity_date=qd.get('validity_date'),
                    commission=qd.get('commission'),
                    total_estimate=qd.get('total_estimate'),
                    included_services=', '.join(qd.get('included_services', [])),
                    notes=qd.get('notes'),
                    raw_summary=qd.get('raw_summary'),
                    source='email',
                    email_log_id=email_log_id,
                )
                db.session.add(q)
                db.session.flush()

                for rr in qd.get('room_rates', []):
                    db.session.add(PartiviaRoomRate(
                        quote_id=q.id, room_type=rr.get('room_type', ''),
                        rate_per_night=rr.get('rate_per_night'),
                        breakfast_included=rr.get('breakfast_included'),
                        notes=rr.get('notes')))
                for mr in qd.get('meeting_rooms', []):
                    db.session.add(PartiviaMeetingRoom(
                        quote_id=q.id, name=mr.get('name', ''),
                        capacity=mr.get('capacity'),
                        rate=mr.get('rate'), notes=mr.get('notes')))
                for fb in qd.get('fb_options', []):
                    db.session.add(PartiviaFBOption(
                        quote_id=q.id, meal_type=fb.get('meal_type', ''),
                        price_per_person=fb.get('price_per_person'),
                        menu_description=fb.get('menu_description')))

                db.session.flush()
                results.append({'hotel': q.hotel_name, 'ok': True,
                                'action': 'added', 'id': q.id})

        db.session.commit()
        return jsonify(ok=True, results=results)

    # ── Edit inline quote ─────────────────────────────────────────────────

    @app.put('/api/partivia/quote/<int:qid>')
    def partivia_update_quote(qid):
        q = PartiviaQuote.query.get_or_404(qid)
        data = request.get_json()
        for field in ('hotel_name', 'city', 'stars', 'contact_name',
                      'contact_email', 'dates_proposed', 'rooms_available',
                      'min_rooms_required', 'cancellation_policy',
                      'payment_terms', 'validity_date', 'commission',
                      'total_estimate', 'included_services', 'notes',
                      'raw_summary', 'quote_status', 'image_url'):
            if field in data:
                val = data[field]
                if field == 'stars' and val is not None:
                    val = int(val) if str(val).strip() else None
                setattr(q, field, val)
        q.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(ok=True)

    @app.delete('/api/partivia/quote/<int:qid>')
    def partivia_delete_quote(qid):
        q = PartiviaQuote.query.get_or_404(qid)
        db.session.delete(q)
        db.session.commit()
        return jsonify(ok=True)

    # ── Edit inline sotto-tabelle ─────────────────────────────────────────

    @app.put('/api/partivia/room-rate/<int:rid>')
    def partivia_update_room_rate(rid):
        rr = PartiviaRoomRate.query.get_or_404(rid)
        data = request.get_json()
        for f in ('room_type', 'rate_per_night', 'breakfast_included', 'notes'):
            if f in data:
                setattr(rr, f, data[f])
        db.session.commit()
        return jsonify(ok=True)

    @app.put('/api/partivia/meeting-room/<int:mid>')
    def partivia_update_meeting_room(mid):
        mr = PartiviaMeetingRoom.query.get_or_404(mid)
        data = request.get_json()
        for f in ('name', 'capacity', 'rate', 'notes'):
            if f in data:
                setattr(mr, f, data[f])
        db.session.commit()
        return jsonify(ok=True)

    @app.put('/api/partivia/fb-option/<int:fid>')
    def partivia_update_fb_option(fid):
        fb = PartiviaFBOption.query.get_or_404(fid)
        data = request.get_json()
        for f in ('meal_type', 'price_per_person', 'menu_description'):
            if f in data:
                setattr(fb, f, data[f])
        db.session.commit()
        return jsonify(ok=True)

    # ── Export Excel comparativo ──────────────────────────────────────────

    @app.get('/api/partivia/export')
    def partivia_export():
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        quotes = (PartiviaQuote.query
                  .order_by(PartiviaQuote.city, PartiviaQuote.hotel_name)
                  .all())

        wb = Workbook()
        header_font = Font(bold=True, color='FFFFFF', size=11)
        header_fill = PatternFill('solid', fgColor='2F5496')
        city_fill = PatternFill('solid', fgColor='D6E4F0')
        city_font = Font(bold=True, size=12)
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin'))
        wrap = Alignment(wrap_text=True, vertical='top')

        # ── Tab 1: Confronto Hotel ──
        ws = wb.active
        ws.title = 'Confronto Hotel'
        headers = [
            'Città', 'Hotel', 'Stelle', 'Camere',
            'Singola/notte', 'Doppia/notte', 'Suite/notte',
            'Sala Meeting', 'Capienza', 'Costo Sala',
            'Pranzo/pax', 'Cena/pax', 'Coffee Break',
            'Totale Stimato', 'Cancellazione', 'Validità',
            'Commissione', 'Servizi Inclusi', 'Contatto', 'Note', 'Stato',
        ]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', wrap_text=True)
            cell.border = thin_border

        for row, q in enumerate(quotes, 2):
            rates = {r.room_type.lower(): r for r in q.room_rates}
            single = next((r for k, r in rates.items()
                           if 'singol' in k), None)
            double = next((r for k, r in rates.items()
                           if 'doppi' in k or 'double' in k or 'twin' in k), None)
            suite = next((r for k, r in rates.items()
                          if 'suite' in k or 'junior' in k), None)
            main_mr = q.meeting_rooms[0] if q.meeting_rooms else None
            fb = {o.meal_type.lower(): o for o in q.fb_options}
            lunch = next((o for k, o in fb.items()
                          if 'pranzo' in k or 'lunch' in k), None)
            dinner = next((o for k, o in fb.items()
                           if 'cena' in k or 'dinner' in k or 'gala' in k), None)
            coffee = next((o for k, o in fb.items()
                           if 'coffee' in k or 'break' in k), None)

            vals = [
                q.city, q.hotel_name, q.stars, q.rooms_available,
                single.rate_per_night if single else '',
                double.rate_per_night if double else '',
                suite.rate_per_night if suite else '',
                main_mr.name if main_mr else '',
                main_mr.capacity if main_mr else '',
                main_mr.rate if main_mr else '',
                lunch.price_per_person if lunch else '',
                dinner.price_per_person if dinner else '',
                coffee.price_per_person if coffee else '',
                q.total_estimate or '',
                q.cancellation_policy or '',
                q.validity_date or '',
                q.commission or '',
                q.included_services or '',
                f'{q.contact_name or ""} {q.contact_email or ""}'.strip(),
                q.notes or '',
                q.quote_status,
            ]
            for col, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=col, value=v)
                cell.border = thin_border
                cell.alignment = wrap

        for col in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 16
        ws.column_dimensions['B'].width = 28
        ws.column_dimensions['R'].width = 30
        ws.column_dimensions['T'].width = 40
        ws.freeze_panes = 'C2'

        # ── Tab 2+: Dettaglio per città ──
        quotes_by_city = {}
        for q in quotes:
            quotes_by_city.setdefault(q.city.upper(), []).append(q)

        for city in sorted(quotes_by_city.keys()):
            cqs = quotes_by_city[city]
            ws_c = wb.create_sheet(title=city[:31])
            ws_c.merge_cells('A1:F1')
            cell = ws_c.cell(row=1, column=1, value=f'Preventivi — {city}')
            cell.font = Font(bold=True, size=14, color='2F5496')

            r = 3
            for q in sorted(cqs, key=lambda x: x.hotel_name):
                ws_c.merge_cells(f'A{r}:F{r}')
                cell = ws_c.cell(row=r, column=1,
                                 value=f"{q.hotel_name} {'★' * (q.stars or 0)}")
                cell.font = city_font
                cell.fill = city_fill
                r += 1
                for label, val in [
                    ('Contatto', f'{q.contact_name or "-"} ({q.contact_email or "-"})'),
                    ('Date', q.dates_proposed or '-'),
                    ('Camere', str(q.rooms_available) if q.rooms_available else '-'),
                    ('Totale', q.total_estimate or '-'),
                    ('Stato', q.quote_status),
                ]:
                    ws_c.cell(row=r, column=1, value=label).font = Font(bold=True)
                    ws_c.cell(row=r, column=2, value=val)
                    r += 1
                if q.room_rates:
                    r += 1
                    ws_c.cell(row=r, column=1,
                              value='TARIFFE CAMERE').font = Font(bold=True, color='2F5496')
                    r += 1
                    for rate in q.room_rates:
                        ws_c.cell(row=r, column=1, value=rate.room_type)
                        ws_c.cell(row=r, column=2, value=rate.rate_per_night)
                        ws_c.cell(row=r, column=3, value=rate.breakfast_included or '')
                        ws_c.cell(row=r, column=4, value=rate.notes or '')
                        r += 1
                if q.meeting_rooms:
                    r += 1
                    ws_c.cell(row=r, column=1,
                              value='SALE MEETING').font = Font(bold=True, color='2F5496')
                    r += 1
                    for mr in q.meeting_rooms:
                        ws_c.cell(row=r, column=1, value=mr.name)
                        ws_c.cell(row=r, column=2, value=mr.capacity or '')
                        ws_c.cell(row=r, column=3, value=mr.rate or '')
                        ws_c.cell(row=r, column=4, value=mr.notes or '')
                        r += 1
                if q.fb_options:
                    r += 1
                    ws_c.cell(row=r, column=1,
                              value='FOOD & BEVERAGE').font = Font(bold=True, color='2F5496')
                    r += 1
                    for fb in q.fb_options:
                        ws_c.cell(row=r, column=1, value=fb.meal_type)
                        ws_c.cell(row=r, column=2, value=fb.price_per_person or '')
                        ws_c.cell(row=r, column=3, value=fb.menu_description or '')
                        r += 1
                r += 1
                ws_c.cell(row=r, column=1,
                          value='CONDIZIONI').font = Font(bold=True, color='2F5496')
                r += 1
                for label, val in [
                    ('Cancellazione', q.cancellation_policy or '-'),
                    ('Pagamento', q.payment_terms or '-'),
                    ('Validità', q.validity_date or '-'),
                    ('Commissione', q.commission or '-'),
                    ('Servizi', q.included_services or '-'),
                ]:
                    ws_c.cell(row=r, column=1, value=label).font = Font(bold=True)
                    ws_c.cell(row=r, column=2, value=val).alignment = wrap
                    r += 1
                if q.notes:
                    ws_c.cell(row=r, column=1, value='Note').font = Font(bold=True)
                    ws_c.cell(row=r, column=2, value=q.notes).alignment = wrap
                    r += 1
                r += 2

            ws_c.column_dimensions['A'].width = 22
            ws_c.column_dimensions['B'].width = 35
            ws_c.column_dimensions['C'].width = 20
            ws_c.column_dimensions['D'].width = 30

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        today = datetime.now().strftime('%Y-%m-%d')
        return send_file(buf, as_attachment=True,
                         download_name=f'partivia_confronto_{today}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── Aggiungi manualmente ──────────────────────────────────────────────

    @app.post('/api/partivia/quote')
    def partivia_add_quote():
        data = request.get_json()
        q = PartiviaQuote(
            hotel_name=data.get('hotel_name', ''),
            city=data.get('city', ''),
            stars=data.get('stars'),
            contact_name=data.get('contact_name'),
            contact_email=data.get('contact_email'),
            dates_proposed=data.get('dates_proposed'),
            rooms_available=data.get('rooms_available'),
            total_estimate=data.get('total_estimate'),
            image_url=data.get('image_url'),
            notes=data.get('notes'),
            source='manual',
        )
        db.session.add(q)
        db.session.commit()
        return jsonify(ok=True, id=q.id)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=os.environ.get('FLASK_DEBUG', '1') == '1', port=5005)
