"""
Radio Tracker — frontend Streamlit v2.

Cambia rispetto alla v1: filtra su trasmesso_il (orario di messa in onda)
e non su inserito_il (orario in cui lo script ha scritto la riga). Con la v1,
una ricerca sui giorni scorsi non restituiva nulla anche a database pieno.
"""

import os
from datetime import datetime, timedelta, time as dtime

import pandas as pd
import requests
import streamlit as st

def conf(nome, default=""):
    """
    Legge un valore dai secret di Streamlit Cloud, altrimenti dall'ambiente.
    In locale basta la variabile d'ambiente (o .streamlit/secrets.toml).
    """
    try:
        if nome in st.secrets:
            return st.secrets[nome]
    except Exception:
        pass                      # nessun file secrets: normale in locale
    return os.environ.get(nome, default)


SUPABASE_URL = conf("SUPABASE_URL", "https://dipwhyetwvqxivxrmqew.supabase.co")
SUPABASE_KEY = conf("SUPABASE_KEY")

st.set_page_config(page_title="Radio Tracker", page_icon="📻", layout="wide")
st.title("📻 Radio Tracker Italia")

if not SUPABASE_KEY:
    st.error("Manca SUPABASE_KEY. Su Streamlit Cloud aggiungila nei Secrets "
             "dell'app; in locale impostala come variabile d'ambiente. "
             "Va usata la chiave PUBBLICA (sb_publishable_... o anon).")
    st.stop()

if str(SUPABASE_KEY).startswith("sb_secret_"):
    st.error("Questa è la chiave SEGRETA e non va messa in un'app web. "
             "Sostituiscila con la chiave pubblica (sb_publishable_...).")
    st.stop()

@st.cache_data(ttl=60)
def stato_raccolta():
    """Quando è stata scritta l'ultima riga, e quante righe ci sono in tutto."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/passaggi_radio",
        headers={"apikey": SUPABASE_KEY, "Prefer": "count=exact"},
        params={"select": "inserito_il", "order": "inserito_il.desc", "limit": "1"},
        timeout=20,
    )
    r.raise_for_status()
    righe = r.json()
    # il totale arriva nell'header Content-Range, es. "0-0/48213"
    totale = None
    cr = r.headers.get("content-range", "")
    if "/" in cr and cr.split("/")[-1].isdigit():
        totale = int(cr.split("/")[-1])
    ultima = righe[0]["inserito_il"] if righe else None
    return ultima, totale


def semaforo():
    """
    Riquadro di stato: la raccolta gira ogni 10 minuti, ma il cron di GitHub
    Actions slitta spesso. Si considera normale fino a un'ora di ritardo.
    """
    try:
        ultima, totale = stato_raccolta()
    except Exception as e:
        st.error(f"Non riesco a leggere il database: {e}")
        return

    if not ultima:
        st.error("Il database è vuoto.")
        return

    ts = pd.to_datetime(ultima, format="ISO8601", utc=True).tz_convert("Europe/Rome")
    ritardo = pd.Timestamp.now(tz="Europe/Rome") - ts
    minuti = int(ritardo.total_seconds() // 60)
    quando = ts.strftime("%d/%m alle %H:%M")
    conteggio = f" · {totale:,} passaggi archiviati".replace(",", ".") if totale else ""

    if minuti < 60:
        st.success(f"Raccolta attiva — ultimo aggiornamento {quando}"
                   f" ({minuti} min fa){conteggio}")
    elif minuti < 180:
        st.warning(f"Nessun dato nuovo da {minuti} minuti (ultimo: {quando})."
                   f" Può essere un ritardo del cron di GitHub.{conteggio}")
    else:
        ore = minuti // 60
        st.error(f"RACCOLTA FERMA da {ore} ore (ultimo dato: {quando}). "
                 f"Controlla il workflow su GitHub → Actions.{conteggio}")


semaforo()

col1, col2 = st.columns([2, 3])
with col1:
    ricerca = st.text_input("Artista o brano", placeholder="es. Cesare Cremonini")
with col2:
    oggi = datetime.now().date()
    periodo = st.date_input(
        "Periodo (messa in onda)",
        value=(oggi - timedelta(days=3), oggi),
        min_value=oggi - timedelta(days=365),
        max_value=oggi,
    )


@st.cache_data(ttl=120)
def interroga(testo, dal, al):
    params = [
        ("brano", f"ilike.*{testo}*"),
        ("trasmesso_il", f"gte.{datetime.combine(dal, dtime.min).isoformat()}"),
        ("trasmesso_il", f"lte.{datetime.combine(al, dtime.max).isoformat()}"),
        ("select", "trasmesso_il,radio,artista,titolo,brano"),
        ("order", "trasmesso_il.desc"),
        ("limit", "10000"),
    ]
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/passaggi_radio",
        headers={"apikey": SUPABASE_KEY},   # qui va la chiave PUBBLICA, mai la secret
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


if ricerca:
    dal = periodo[0] if periodo else oggi
    al = periodo[1] if len(periodo) == 2 else dal

    try:
        dati = interroga(ricerca, dal, al)
    except Exception as e:
        st.error(f"Errore nella query: {e}")
        st.stop()

    if not dati:
        st.warning("Nessun passaggio trovato in questo periodo.")
        st.stop()

    df = pd.DataFrame(dati)
    # I timestamp arrivano in due formati: quelli recuperati dal sito hanno
    # offset +02:00 senza microsecondi, quelli migrati dalle righe vecchie
    # hanno microsecondi e +00:00. format="ISO8601" li accetta entrambi,
    # utc=True li normalizza, poi si riportano all'ora italiana.
    df["trasmesso_il"] = (
        pd.to_datetime(df["trasmesso_il"], format="ISO8601", utc=True)
          .dt.tz_convert("Europe/Rome")
    )

    # le righe raccolte prima della migrazione non hanno artista/titolo separati
    mancanti = df["artista"].isna()
    if mancanti.any():
        split = df.loc[mancanti, "brano"].str.split(" - ", n=1, expand=True)
        df.loc[mancanti, "artista"] = split[0]
        df.loc[mancanti, "titolo"] = split[1] if split.shape[1] > 1 else "-"

    # Più artisti possono avere un brano con lo stesso titolo (es. "Paparazzi"
    # di Cremonini e di Lady Gaga). La ricerca gira su "ARTISTA - TITOLO", quindi
    # li pesca entrambi: qui si isola quello che interessa.
    conteggi = df["artista"].fillna("—").value_counts()
    etichette = {f"{a} ({n})": a for a, n in conteggi.items()}

    if len(etichette) > 1:
        scelti = st.multiselect(
            f"Trovati {len(etichette)} artisti — lascia vuoto per vederli tutti",
            options=list(etichette.keys()),
        )
        if scelti:
            df = df[df["artista"].isin([etichette[e] for e in scelti])]
            if df.empty:
                st.warning("Nessun passaggio per gli artisti selezionati.")
                st.stop()

    a, b, c = st.columns(3)
    a.metric("Passaggi totali", len(df))
    b.metric("Emittenti", df["radio"].nunique())
    c.metric("Brani distinti", df["titolo"].nunique())

    st.subheader("Passaggi per emittente")
    st.bar_chart(df["radio"].value_counts())

    st.subheader("Passaggi per giorno")
    st.bar_chart(df.set_index("trasmesso_il").resample("D").size())

    vista = df.assign(
        Data=df["trasmesso_il"].dt.strftime("%d/%m/%Y"),
        Ora=df["trasmesso_il"].dt.strftime("%H:%M"),
    )[["Data", "Ora", "radio", "artista", "titolo"]]
    vista.columns = ["Data", "Ora", "Emittente", "Artista", "Titolo"]

    st.dataframe(vista, use_container_width=True, hide_index=True)
    st.download_button(
        "Scarica CSV",
        vista.to_csv(index=False).encode("utf-8"),
        file_name=f"passaggi_{ricerca}_{dal}_{al}.csv",
        mime="text/csv",
    )
else:
    st.info("Scrivi un artista o un brano per iniziare.")
