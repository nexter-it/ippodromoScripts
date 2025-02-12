#!/usr/bin/env python3
import socket
import json
import subprocess

# Impostazioni
UDP_IP = "0.0.0.0"
UDP_PORT = 5959
CONFIG_FILE = "/home/pi/config.json"
SERVICE_TO_RESTART = "horsemonitor.service"

def update_config(horse_number):
    """
    Legge il file di configurazione, aggiorna il valore di HEAD_ID e lo riscrive.
    """
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    except Exception as e:
        print(f"[ERRORE] Lettura del file {CONFIG_FILE}: {e}")
        return False

    # Aggiorna o imposta il valore di HEAD_ID
    config["HEAD_ID"] = horse_number

    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"[ERRORE] Scrittura del file {CONFIG_FILE}: {e}")
        return False

    print(f"[INFO] Aggiornato HEAD_ID a {horse_number} in {CONFIG_FILE}")
    return True

def restart_service():
    """
    Riavvia il servizio utilizzando systemctl.
    È necessario che l'utente che esegue lo script abbia i permessi per
    eseguire il comando 'sudo systemctl restart horsemonitor.service' senza password.
    """
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", SERVICE_TO_RESTART],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[ERRORE] Riavvio servizio: {result.stderr}")
        else:
            print(f"[INFO] Servizio {SERVICE_TO_RESTART} riavviato correttamente.")
    except Exception as e:
        print(f"[ERRORE] Esecuzione comando di riavvio: {e}")

def main():
    # Crea il socket UDP e lo mette in ascolto
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"[INFO] In ascolto su UDP {UDP_IP}:{UDP_PORT}...")

    while True:
        try:
            data, addr = sock.recvfrom(1024)  # Buffer da 1024 byte
            print(f"[INFO] Ricevuto pacchetto da {addr}")

            try:
                message = json.loads(data.decode('utf-8'))
            except json.JSONDecodeError as e:
                print(f"[ERRORE] JSON non valido: {e}")
                continue

            # Verifica che la chiave "horse_number" sia presente
            if "horse_number" not in message:
                print("[ERRORE] Chiave 'horse_number' non trovata nel pacchetto ricevuto.")
                continue

            horse_number = message["horse_number"]
            print(f"[INFO] Imposto HEAD_ID a: {horse_number}")

            # Aggiorna il file di configurazione e riavvia il servizio se l'aggiornamento ha avuto successo
            if update_config(horse_number):
                restart_service()

        except KeyboardInterrupt:
            print("\n[INFO] Interrotto dall'utente. Uscita...")
            break
        except Exception as e:
            print(f"[ERRORE] {e}")

if __name__ == "__main__":
    main()
