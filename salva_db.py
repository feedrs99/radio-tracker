import requests
from bs4 import BeautifulSoup
import re

# --- CONFIGURAZIONE SUPABASE ---
# Questo è l'URL esatto del tuo progetto
SUPABASE_URL = "https://dipwhyetwvqxivxrmqew.supabase.co"  

# QUI devi incollare la tua chiave API di Supabase, mantenendo le virgolette
SUPABASE_KEY = "sb_publishable_lZTca_D91sbCdrp5a0k_JA_92S1lHz5"      

def invia_a_supabase(passaggi):
    if not passaggi:
        print("Nessun passaggio trovato da inviare.")
        return

    url = f"{SUPABASE_URL}/rest/v1/passaggi_radio"
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=ignore-duplicates"
    }

    try:
        response = requests.post(url, headers=headers, json=passaggi)
        if response.status_code in [200, 201]:
            print(f"✅ Sincronizzazione completata! Elaborati {len(passaggi)} brani (doppioni scartati).")
        else:
            print(f"❌ Errore da Supabase: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Errore di connessione a Supabase: {e}")

def estrai_e_salva():
    url = "https://myradioonline.it/playlists"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    print("Scaricando i dati recenti dall'aggregatore...")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Errore di connessione al sito: {response.status_code}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        testo_puro = soup.get_text(separator='\n')
        righe = [riga.strip() for riga in testo_puro.split('\n') if riga.strip()]
        
        passaggi = []

        for i in range(len(righe) - 1):
            riga_attuale = righe[i]
            riga_successiva = righe[i+1]
            
            match = re.match(r"(\d{2}\.\d{2})\s+(\d{2}:\d{2})\s+-\s+(.+)", riga_attuale)
            
            if match:
                ora = match.group(2)
                nome_radio = match.group(3).strip()
                canzone = riga_successiva.strip()
                
                if canzone != "-" and "pubblicita" not in canzone.lower() and "diretta" not in canzone.lower():
                    passaggi.append({
                        "radio": nome_radio,
                        "brano": canzone,
                        "orario": ora
                    })

        invia_a_supabase(passaggi)

    except Exception as e:
        print(f"Si è verificato un errore: {e}")

if __name__ == "__main__":
    estrai_e_salva()