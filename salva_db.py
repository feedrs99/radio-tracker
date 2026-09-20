"""
Raccolta continua v2 — girato da GitHub Actions ogni 10 minuti.

Differenze rispetto alla v1:
  - non fa più il parsing a regex della homepage (che sbagliava ad associare
    il nome della radio alla canzone della riga successiva)
  - interroga la playlist di ogni emittente con lo stesso endpoint dello
    storico, quindi salva l'orario REALE di messa in onda e l'id univoco
  - se un run salta (GitHub Actions non è puntuale), il run dopo recupera
    comunque le prime 3 pagine = ~13 ore di rotazione
"""

from radio_core import (
    RADIOS, sessione, leggi_hash, scarica_pagina, estrai,
    invia_a_supabase, pausa,
)

PAGINE = 3   # 3 x 45 = 135 passaggi per radio, copre eventuali run saltati


def main():
    s = sessione()
    for nome, slug in RADIOS:
        try:
            h = leggi_hash(s, slug)
        except Exception as e:
            print(f"[{nome}] saltata: {e}")
            continue

        raccolti = 0
        for pagina in range(1, PAGINE + 1):
            try:
                righe = estrai(scarica_pagina(s, slug, h, "", "", pagina), nome)
                if not righe:
                    break
                raccolti += invia_a_supabase(righe)
                pausa()
            except Exception as e:
                print(f"[{nome}] p{pagina}: {e}")
                break

        print(f"[{nome}] {raccolti} passaggi inviati")


if __name__ == "__main__":
    main()
