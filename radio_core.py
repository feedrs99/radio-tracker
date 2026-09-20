"""
Radio Tracker — libreria condivisa.

Parla con l'endpoint AJAX reale di myradioonline.it, quello che il sito usa
quando clicchi "Pagina successiva" o filtri per data:

    POST https://myradioonline.it/<slug>/playlist
    Content-Type: application/x-www-form-urlencoded
    ajax=1&name=&from=YYYY-MM-DD&to=YYYY-MM-DD&hash=&actPage=N&lastId=0

    -> {"html": "<frammento html con 45 passaggi>"}

Note verificate sul campo:
  - Gli header Referer/Origin/Accept sono OBBLIGATORI. Senza, il sito
    restituisce la pagina HTML intera invece della risposta AJAX.
  - Il JSON viene servito con content-type "text/html": non fidarsi
    dell'header, provare direttamente il parse.
  - Il campo "hash" (canale) puo' restare VUOTO: il sito usa il canale
    principale, con risultati identici. Serve solo per i sotto-canali
    (Deejay One Love, Deejay 80, ecc.).
  - Storico disponibile: 30 giorni.

Ogni passaggio nel frammento HTML porta con se':
  - meta[itemprop=identifier]  -> id univoco (chiave di deduplica)
  - [itemprop=startDate]       -> timestamp ISO con fuso, 2026-09-17T19:22:05+02:00
  - [itemprop=byArtist]        -> artista
  - [itemprop=name]            -> titolo
"""

import os
import time
import requests
from bs4 import BeautifulSoup

BASE = "https://myradioonline.it"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# --- Supabase -------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dipwhyetwvqxivxrmqew.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# --- Emittenti monitorate -------------------------------------------------
# Le 20 nazionali che contano per l'airplay musicale.
RADIOS = [
    ("RTL 102.5",             "rtl-102-5"),
    ("Radio Deejay",          "radio-deejay"),
    ("RDS",                   "radio-dimensione-suono"),
    ("Radio 105",             "radio-105"),
    ("Radio Italia",          "radio-italia"),
    ("Radio Kiss Kiss",       "radio-kiss-kiss"),
    ("Radio Zeta",            "radio-zeta"),
    ("R101",                  "r101"),
    ("Virgin Radio",          "virgin-radio"),
    ("M2O",                   "m2o"),
    ("Radio Capital",         "radio-capital"),
    ("Radio Subasio",         "radio-subasio"),
    ("Radio Monte Carlo",     "radio-monte-carlo"),
    ("Radiofreccia",          "radiofreccia"),
    ("Radio Norba",           "radio-norba"),
    ("LatteMiele",            "lattemiele"),
    ("Radio Bruno",           "radio-bruno"),
    ("Radio Nostalgia",       "radio-nostalgia"),
    ("Dimensione Suono Roma", "dimensione-suono-roma"),
    ("Radio Globo",           "radio-globo"),
]

# Le altre 56 emittenti con playlist interrogabile, verificate il 20/09/2026.
# Per aggiungerne una, spostala nella lista RADIOS qui sopra.
ALTRE_DISPONIBILI = [
    ("70-80.it", "70-80-it"), ("Antenna 1", "antenna-1"),
    ("Controradio", "controradio"), ("Daddy Radio", "daddy-radio"),
    ("FM Italia", "fm-italia"), ("Gargano FM", "gargano-fm"),
    ("Gelosa", "gelosa"), ("Globo Vintage", "globo-vintage"),
    ("Italia News 24", "italia-news-24"),
    ("Italian's News Radio", "italian-s-news-radio"),
    ("LifeGate Radio", "lifegate-radio"), ("Mazda Radio", "mazda-radio"),
    ("Musica Vera", "musica-vera"), ("No Name Radio", "no-name-radio"),
    ("Radio 80", "radio-80"), ("Radio Babboleo", "radio-babboleo"),
    ("Radio Birikina", "radio-birikina"), ("Radio California", "radio-california"),
    ("Radio Cecchetto", "radio-cecchetto"), ("Radio Company", "radio-company"),
    ("Radio Easy Network", "radio-easy-network"), ("Radio Easy Rock", "radio-easy-rock"),
    ("Radio Italia Anni 60", "radio-italia-anni-60"), ("Radio JukeBox", "radio-jukebox"),
    ("Radio Manila", "radio-manila"), ("Radio Margherita", "radio-margherita"),
    ("Radio MaRilu", "radio-marilu"), ("Radio Marte", "radio-marte"),
    ("Radio Michelle", "radio-michelle-amore-senza-fine"),
    ("Radio Mitology", "radio-mitology"), ("Radio Monte Carlo 2", "radio-monte-carlo-2"),
    ("Radio Nord Castrovillari", "radio-nord-castrovillari"),
    ("Radio Number One", "radio-number-one"),
    ("Radio Nuova San Giorgio", "radio-nuova-san-giorgio"),
    ("Radio Octopus", "radio-octopus"), ("ANNi 90", "radio-ottanta"),
    ("Radio Pico", "radio-pico"), ("Radio Punto Zero", "radio-punto-zero"),
    ("Radio Roma", "radio-roma"), ("Radio Romeo & Juliet", "radio-romeo-juliet"),
    ("Radio Saba Sound", "radio-saba-sound"), ("Radio Silver", "radio-silver"),
    ("Radio Stella", "radio-stella"), ("Radio Studio 104", "radio-studio-104"),
    ("Radio Studio Nord", "radio-studio-nord"), ("Radio Verona", "radio-verona"),
    ("Radio Versilia", "radio-versilia-rfm-tv-inblu"), ("Radio WOW", "radio-wow"),
    ("Rai Isoradio", "rai-isoradio"), ("Rai Radio 3", "rai-radio-3"),
    ("RAM Power", "ram-power"), ("RDS Relax", "rds-relax"),
    ("Romantica Radio", "romantica-radio"), ("Simply Radio", "simply-radio"),
    ("Stereocitta", "stereocitta"), ("Sudtirol 1", "sudtirol-1"),
]


def sessione():
    """Sessione per myradioonline: si presenta come un browser."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


# Sessione SEPARATA per Supabase, con uno User-Agent non-browser.
# Supabase rifiuta le secret key quando la richiesta sembra venire da un
# browser ("Forbidden use of secret API key in browser"), e lo capisce dallo
# User-Agent. Riusare la sessione di scraping fa scattare il blocco.
_supabase = requests.Session()
_supabase.headers.update({"User-Agent": "radiotracker/2.0 (python-requests)"})


def scarica_pagina(s, slug, dal, al, pagina):
    """Una pagina (45 passaggi). dal/al = 'YYYY-MM-DD', oppure '' per il live."""
    r = s.post(
        f"{BASE}/{slug}/playlist",
        data={
            "ajax": "1", "name": "", "from": dal, "to": al,
            "hash": "", "actPage": str(pagina), "lastId": "0",
        },
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{BASE}/{slug}/playlist",
            "Origin": BASE,
            "Accept-Language": "it-IT,it;q=0.9",
        },
        timeout=25,
    )
    r.raise_for_status()
    try:
        return r.json().get("html", "")
    except ValueError:
        raise RuntimeError(
            f"risposta non-JSON: HTTP {r.status_code}, "
            f"content-type={r.headers.get('content-type')!r}, "
            f"inizio corpo={r.text[:160]!r}"
        )


def estrai(html, nome_radio):
    """Frammento HTML -> lista di dict pronti per Supabase."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for item in soup.select(".plist-item"):
        pid = item.get("data-id")
        sd = item.select_one('[itemprop="startDate"]')
        art = item.select_one('[itemprop="byArtist"]')
        tit = item.select_one('[itemprop="name"]')
        if not (pid and sd and sd.get("content")):
            continue

        artista = art.get_text(strip=True) if art else ""
        titolo = tit.get_text(strip=True) if tit else ""
        brano = f"{artista} - {titolo}".strip(" -")
        if not brano or "pubblicit" in brano.lower():
            continue

        ts = sd["content"]
        out.append({
            "passaggio_id": int(pid),
            "radio": nome_radio,
            "brano": brano,
            "artista": artista,
            "titolo": titolo,
            "orario": ts[11:16],
            "trasmesso_il": ts,
        })
    return out


class ChiaveRifiutata(RuntimeError):
    """Credenziali sbagliate: inutile ritentare, si ferma tutto."""


def invia_a_supabase(passaggi):
    """
    Upsert ignorando i duplicati.
    on_conflict=passaggio_id e' OBBLIGATORIO: senza, PostgREST guarda solo la
    primary key (id, autogenerata) e la POST fallisce con 409 sui duplicati.
    """
    if not passaggi:
        return 0
    r = _supabase.post(
        f"{SUPABASE_URL}/rest/v1/passaggi_radio?on_conflict=passaggio_id",
        headers={
            "apikey": SUPABASE_KEY,
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates,return=minimal",
        },
        json=passaggi,
        timeout=60,
    )
    if r.status_code in (401, 403):
        raise ChiaveRifiutata(f"Supabase {r.status_code}: {r.text[:300]}")
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
    return len(passaggi)


def pausa(sec=0.6):
    time.sleep(sec)
