import socket
import base64
import binascii
import serial
import threading
import time
import argparse
from datetime import datetime
import pynmea2
from collections import deque

# Parametri di connessione al caster NTRIP
NTRIP_HOST = '213.209.192.165'
NTRIP_PORT = 2101
MOUNTPOINT = 'NEXTER'
USERNAME = 'nexter'
PASSWORD = 'nexter25'

# Parametri di connessione GPS
GPS_PORT = '/dev/ttyACM0'
GPS_BAUDRATE = 115200

# Parametri di connessione al server di destinazione (UDP)
DEST_HOST = '10.0.0.1'
DEST_PORT = 3131

# Nuovo server di destinazione aggiuntivo
SECOND_DEST_HOST = '213.209.192.165'
SECOND_DEST_PORT = 5001

# Variabili globali
rtcm_data = b''
rtcm_lock = threading.Lock()
gps_position = None
gps_lock = threading.Lock()
last_rtcm_time = 0
RTCM_MIN_INTERVAL = 1.0  # Intervallo di 1 secondo tra le correzioni RTCM

# Per il calcolo degli hertz
gps_update_times = deque(maxlen=100)
hertz_lock = threading.Lock()
current_hertz = 0

# ----> Socket UDP globale
udp_socket = None
second_udp_socket = None

def connect_to_ntrip():
    """Connessione al caster NTRIP e ricezione delle correzioni RTCM"""
    global rtcm_data
    
    credentials = f"{USERNAME}:{PASSWORD}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    request = (
        f"GET /{MOUNTPOINT} HTTP/1.1\r\n"
        f"User-Agent: NTRIP PythonClient/1.0\r\n"
        f"Authorization: Basic {encoded_credentials}\r\n"
        f"Ntrip-Version: NTRIP/2.0\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            print("Connessione al caster NTRIP...")
            s.connect((NTRIP_HOST, NTRIP_PORT))
            s.sendall(request.encode())
            
            response = s.recv(1024)
            if b"ICY 200 OK" not in response:
                print("Errore nella connessione al caster NTRIP")
                return
            
            while True:
                data = s.recv(1024)
                if not data:
                    break
                
                with rtcm_lock:
                    rtcm_data = data
                
    except Exception as e:
        print(f"Errore nella connessione NTRIP: {e}")

def init_udp_sockets():
    """Inizializza i socket UDP una sola volta."""
    global udp_socket, second_udp_socket
    try:
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        second_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print("Socket UDP inizializzati correttamente.")
    except Exception as e:
        print(f"Errore nell'inizializzazione dei socket UDP: {e}")

def send_gps_data(gps_data):
    """Invia i dati GPS ai server di destinazione tramite UDP usando i socket globali."""
    global udp_socket, second_udp_socket
    if udp_socket is None or second_udp_socket is None:
        print("Socket UDP non inizializzati!")
        return
    
    try:
        # Invia al primo destinatario
        udp_socket.sendto(gps_data.encode(), (DEST_HOST, DEST_PORT))
        
        # Invia al secondo destinatario
        second_udp_socket.sendto(gps_data.encode(), (SECOND_DEST_HOST, SECOND_DEST_PORT))
    except Exception as e:
        print(f"Errore nell'invio dei dati GPS: {e}")

def update_hertz():
    """Calcola e aggiorna la frequenza di aggiornamento dei dati GPS in Hz"""
    global current_hertz
    
    while True:
        time.sleep(1)  # Aggiorna la frequenza ogni secondo
        
        with hertz_lock:
            now = time.time()
            # Rimuovi i timestamp più vecchi di 1 secondo
            while gps_update_times and now - gps_update_times[0] > 1.0:
                gps_update_times.popleft()
            
            # Il numero di aggiornamenti nell'ultimo secondo è la frequenza in Hz
            # Dividi per 3 come richiesto
            current_hertz = len(gps_update_times) / 3
            
            print(f"Frequenza attuale: {current_hertz} Hz")

def connect_to_gps():
    """Connessione al ricevitore GPS e lettura dei dati NMEA"""
    global gps_position
    
    try:
        with serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1) as ser:
            print(f"Connessione al GPS sulla porta {GPS_PORT}...")
            
            while True:
                try:
                    line = ser.readline().decode('ascii', errors='replace').strip()
                    
                    if line.startswith('$'):
                        # Aggiorna il timestamp per il calcolo degli hertz
                        with hertz_lock:
                            gps_update_times.append(time.time())
                        
                        # Invia tutti i dati NMEA ai server tramite UDP
                        send_gps_data(line)
                        
                        try:
                            msg = pynmea2.parse(line)
                            
                            if isinstance(msg, pynmea2.GGA):
                                with gps_lock:
                                    gps_position = {
                                        'lat': msg.latitude,
                                        'lon': msg.longitude,
                                        'alt': msg.altitude,
                                        'quality': msg.gps_qual,
                                        'satellites': msg.num_sats,
                                        'hdop': msg.horizontal_dil,
                                        'time': msg.timestamp,
                                        'raw': line,
                                        'hertz': current_hertz  # Aggiungi la frequenza attuale
                                    }
                                
                                # Invia correzioni RTCM ogni secondo
                                current_time = time.time()
                                with rtcm_lock:
                                    global last_rtcm_time
                                    if rtcm_data and (current_time - last_rtcm_time) >= RTCM_MIN_INTERVAL:
                                        ser.write(rtcm_data)
                                        last_rtcm_time = current_time
                                
                        except pynmea2.ParseError:
                            pass
                
                except Exception as e:
                    print(f"Errore nella lettura GPS: {e}")
                    time.sleep(1)
    
    except Exception as e:
        print(f"Errore nella connessione GPS: {e}")

def parse_arguments():
    """Funzione per gestire i parametri da linea di comando"""
    parser = argparse.ArgumentParser(description='Sistema GPS-RTK con correzioni NTRIP')
    
    parser.add_argument('--gps-port', dest='gps_port', default=GPS_PORT,
                        help=f'Porta seriale del ricevitore GPS (default: {GPS_PORT})')
    
    parser.add_argument('--dest-ip', dest='dest_ip', default=DEST_HOST,
                        help=f'Indirizzo IP del server di destinazione (default: {DEST_HOST})')
    
    parser.add_argument('--dest-port', dest='dest_port', type=int, default=DEST_PORT,
                        help=f'Porta UDP del server di destinazione (default: {DEST_PORT})')
    
    parser.add_argument('--second-dest-ip', dest='second_dest_ip', default=SECOND_DEST_HOST,
                        help=f'Indirizzo IP del secondo server di destinazione (default: {SECOND_DEST_HOST})')
    
    parser.add_argument('--second-dest-port', dest='second_dest_port', type=int, default=SECOND_DEST_PORT,
                        help=f'Porta UDP del secondo server di destinazione (default: {SECOND_DEST_PORT})')
    
    return parser.parse_args()

def main():
    # Parsing dei parametri da linea di comando
    args = parse_arguments()
    
    # Aggiorna i parametri globali con quelli forniti da linea di comando
    global GPS_PORT, DEST_HOST, DEST_PORT, SECOND_DEST_HOST, SECOND_DEST_PORT
    GPS_PORT = args.gps_port
    DEST_HOST = args.dest_ip
    DEST_PORT = args.dest_port
    SECOND_DEST_HOST = args.second_dest_ip
    SECOND_DEST_PORT = args.second_dest_port
    
    print(f"Utilizzando porta GPS: {GPS_PORT}")
    print(f"Inviando dati a: {DEST_HOST}:{DEST_PORT}")
    print(f"Inviando dati a: {SECOND_DEST_HOST}:{SECOND_DEST_PORT}")
    
    # Inizializza i socket UDP una sola volta
    init_udp_sockets()
    
    # Avvia i thread
    ntrip_thread = threading.Thread(target=connect_to_ntrip)
    gps_thread = threading.Thread(target=connect_to_gps)
    hertz_thread = threading.Thread(target=update_hertz)
    
    ntrip_thread.daemon = True
    gps_thread.daemon = True
    hertz_thread.daemon = True
    
    ntrip_thread.start()
    gps_thread.start()
    hertz_thread.start()
    
    print("Sistema GPS-RTK avviato. Premi Ctrl+C per terminare.")
    
    try:
        while True:
            time.sleep(1)
            # Stampa informazioni sulla posizione e sulla frequenza
            with gps_lock:
                if gps_position:
                    print(f"Posizione: Lat: {gps_position['lat']}, Lon: {gps_position['lon']}, "
                          f"Qualità: {gps_position['quality']}, Hz: {current_hertz}")
    except KeyboardInterrupt:
        print("\nProgramma terminato dall'utente")

if __name__ == "__main__":
    main()
