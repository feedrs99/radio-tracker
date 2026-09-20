"""
Raccolta continua — girata da GitHub Actions ogni 10 minuti.

Legge le prime pagine della playlist di ogni emittente e salva le righe nuove.
3 pagine = ~135 passaggi a testa = oltre 12 ore di rotazione: cosi' anche se
il cron di GitHub salta qualche giro non si perde niente.

Serve la chiave SEGRETA in SUPABASE_KEY.
"""

import concurrent.futures as cf

from radio_core import (
    RADIOS, sessione, scarica_pagina, estrai,
    invia_a_supabase, pausa, ChiaveRifiutata,
)

PAGINE = 3


def raccogli(radio):
    nome, slug = radio
    s = sessione()
    raccolti = 0

    for pagina in range(1, PAGINE + 1):
        try:
            righe = estrai(scarica_pagina(s, slug, "", "", pagina), nome)
            if not righe:
                break
            raccolti += invia_a_supabase(righe)
            pausa(0.4)
        except ChiaveRifiutata:
            raise
        except Exception as e:
            print(f"[{nome}] p{pagina}: {e}")
            break

    print(f"[{nome}] {raccolti} passaggi inviati")
    return raccolti


def main():
    try:
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            totali = list(ex.map(raccogli, RADIOS))
    except ChiaveRifiutata as e:
        # esce con errore: cosi' il run su GitHub diventa rosso e te ne accorgi
        raise SystemExit(f"Supabase rifiuta la chiave: {e}")

    print(f"\nTotale inviato: {sum(totali)} righe su {len(RADIOS)} emittenti")


if __name__ == "__main__":
    main()
