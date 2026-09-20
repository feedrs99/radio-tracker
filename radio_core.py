"""
Radio Tracker — libreria condivisa.

Parla con l'endpoint AJAX reale di myradioonline.it, quello che il sito usa
quando clicchi "Pagina successiva" o filtri per data:

    POST https://myradioonline.it/<slug>/playlist
    Content-Type: application/x-www-form-urlencoded
    ajax=1&name=&from=YYYY-MM-DD&to=YYYY-MM-DD&hash=<hash canale>&actPage=N&lastId=0

    -> {"html": "<frammento html con i passaggi>"}

Ogni passaggio nel frammento HTML porta con sé:
  - meta[itemprop=identifier]  -> id univoco del passaggio (chiave di deduplica)
  - [itemprop=startDate]       -> timestamp ISO COMPLETO con fuso, es. 2026-09-17T19:22:05+02:00
  - [itemprop=byArtist]        -> artista
  - [itemprop=name]            -> titolo

Storico disponibile: 30 giorni (data-minday="-30d" sui campi data del sito).
"""

import os
import time
import requests
from bs4 import BeautifulSoup

BASE = "https://myradioonline.it"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"

# --- Supabase -------------------------------------------------------------
# Meglio da variabile d'ambiente che hardcoded (vedi note nel README).
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dipwhyetwvqxivxrmqew.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "LA_TUA_CHIAVE_ANON_PUBLIC")

# --- Emittenti ------------------------------------------------------------
# ATTENZIONE agli slug: due della tua lista erano sbagliati.
#   "rds"                                -> 404   (giusto: radio-dimensione-suono)
#   "radio-italia-solo-musica-italiana"  -> la pagina esiste ma NON ha playlist
#                                           tracciata su questo aggregatore
RADIOS = [
    ("Radio Deejay",    "radio-deejay"),
    ("RTL 102.5",       "rtl-102-5"),
    ("RDS",             "radio-dimensione-suono"),
    ("Radio 105",       "radio-105"),
    ("Radio Kiss Kiss", "radio-kiss-kiss"),
]

# hash del canale principale, letti dal sito il 20/09/2026.
# Se una radio smette di funzionare, cancella la sua voce da qui:
# lo script se lo rilegge da solo dalla pagina.
HASH_CACHE = {
    "radio-deejay":           "3c501862a439aefb5aec7b3122b3ac85",
    "rtl-102-5":              "6873b6635cd1b4b5d224aea4eaf94380",
    "radio-dimensione-suono": "f85ccc43f0fcca95235ec5f38d739b45",
    "radio-105":              "13f0577929c4e7f77faffb0d60612d93",
    "radio-kiss-kiss":        "18dbd254eae7bc3a8b583ce4a08ab162",
}


def sessione():
    """Sessione per myradioonline: si presenta come un browser."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


# Sessione SEPARATA per Supabase, con uno User-Agent non-browser.
# Serve: Supabase rifiuta le secret key quando la richiesta sembra venire da
# un browser ("Forbidden use of secret API key in browser"), e lo capisce
# dallo User-Agent. Riusare la sessione di scraping fa scattare il blocco.
_supabase = requests.Session()
_supabase.headers.update({"User-Agent": "radiotracker/2.0 (python-requests)"})


def leggi_hash(s, slug):
    """
    Carica la pagina playlist e ne estrae l'hash del canale principale.

    La GET serve anche a un secondo scopo: raccogliere i cookie di sessione.
    Il sito serve la risposta AJAX in JSON solo a una sessione che ha già
    visitato la pagina; a freddo restituisce HTML e il parsing JSON esplode.
    """
    r = s.get(f"{BASE}/{slug}/playlist", timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    sel = soup.select_one('select[name="hash"] option')
    if sel:
        HASH_CACHE[slug] = sel["value"]
        return sel["value"]
    if slug in HASH_CACHE:          # struttura cambiata: ripiego sulla cache
        return HASH_CACHE[slug]
    raise RuntimeError(f"{slug}: nessuna playlist tracciata su questo sito")


def scarica_pagina(s, slug, hash_canale, dal, al, pagina):
    """Una pagina (45 passaggi) di playlist. dal/al = 'YYYY-MM-DD' o ''."""
    r = s.post(
        f"{BASE}/{slug}/playlist",
        data={
            "ajax": "1",
            "name": "",
            "from": dal,
            "to": al,
            "hash": hash_canale,
            "actPage": str(pagina),
            "lastId": "0",
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
    # ATTENZIONE: il sito serve il JSON con content-type "text/html".
    # Non fidarsi dell'header: si prova a fare il parse e basta.
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

        ts = sd["content"]                      # 2026-09-17T19:22:05+02:00
        out.append({
            "passaggio_id": int(pid),
            "radio": nome_radio,
            "brano": brano,
            "artista": artista,
            "titolo": titolo,
            "orario": ts[11:16],                # "19:22", per compatibilità
            "trasmesso_il": ts,
        })
    return out


class ChiaveRifiutata(RuntimeError):
    """Credenziali sbagliate: inutile ritentare, si ferma tutto."""


def invia_a_supabase(passaggi, s=None):
    """
    Upsert ignorando i duplicati.
    on_conflict=passaggio_id è OBBLIGATORIO: senza, PostgREST guarda solo la
    primary key (id, autogenerata) e la POST fallisce con 409 sui duplicati.

    Il parametro `s` è ignorato di proposito: si usa sempre la sessione
    dedicata, mai quella con lo User-Agent da browser.
    """
    if not passaggi:
        return 0
    r = _supabase.post(
        f"{SUPABASE_URL}/rest/v1/passaggi_radio?on_conflict=passaggio_id",
        # Solo header "apikey": è quello richiesto dalle chiavi nuove
        # (sb_secret_...) e funziona anche con la service_role legacy.
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
