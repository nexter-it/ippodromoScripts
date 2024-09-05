import socket
import time

# Configurazione del server UDP
LISTEN_IP = '192.168.4.1'  # L'indirizzo IP di wlan0
LISTEN_PORT = 4141  # Porta su cui il server ascolta i pacchetti

# Indirizzo IP e porta del server a cui inoltrare i dati
FORWARD_IP = '95.230.211.208'
FORWARD_PORT = 4141

def create_socket():
    """Crea un socket UDP per il server."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((LISTEN_IP, LISTEN_PORT))
    return s

def forward_data(sock, data):
    """Inoltra i dati ricevuti a un altro server."""
    try:
        sock.sendto(data, (FORWARD_IP, FORWARD_PORT))
        print(f"OUT to [{FORWARD_IP}]: {data.decode('utf-8')}")
    except socket.error as e:
        print(f"Errore di invio: {e}")

def start_server():
    """Avvia il server UDP che riceve pacchetti e li inoltra."""
    sock = create_socket()
    print(f"Server avviato su {LISTEN_IP}:{LISTEN_PORT}. Inoltramento verso {FORWARD_IP}:{FORWARD_PORT}")

    try:
        while True:
            data, addr = sock.recvfrom(1024)  # Riceve i pacchetti (dimensione max 1024 byte)
            print(f"IN from sensor [{data.decode('utf-8').split(',')[2]}]: {data.decode('utf-8')} da {addr}")
            forward_data(sock, data)  # Inoltra i dati ricevuti
            time.sleep(0.002)  # Aggiungi un breve ritardo se necessario

    except KeyboardInterrupt:
        print("Server interrotto dall'utente.")
    except Exception as e:
        print(f"Errore: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    start_server()
