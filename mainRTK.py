#!/usr/bin/env python3
# filepath: gps_rtk_client.py

import socket
import base64
import serial
import threading
import time
import argparse
import pynmea2
import sys
from collections import deque

# Flag per il controllo dell'esecuzione
running = True

# Configurazione di default
config = {
    # NTRIP
    "ntrip_host": "213.209.192.165",
    "ntrip_port": 2101,
    "ntrip_mountpoint": "NEXTER",
    "ntrip_username": "nexter",
    "ntrip_password": "nexter25",
    "ntrip_retry": 5,
    
    # GPS
    "gps_port": "/dev/ttyACM0",
    "gps_baudrate": 115200,
    "gps_retry": 3,
    
    # RTCM
    "rtcm_interval": 1.0,
    
    # Destinazioni (lista di tuple (host, porta))
    "destinations": [
        ("10.0.0.3", 3131),
        ("213.209.192.165", 5001)
    ]
}

# Variabili globali
rtcm_data = b''
rtcm_lock = threading.Lock()
gps_position = None
gps_lock = threading.Lock()
last_rtcm_time = 0

# Per il calcolo degli hertz
gps_update_times = deque(maxlen=100)
hertz_lock = threading.Lock()
current_hertz = 0

# Socket UDP
udp_sockets = []

def init_udp_sockets():
    """Inizializza i socket UDP per tutte le destinazioni."""
    global udp_sockets
    
    # Chiudi eventuali socket esistenti
    for sock in udp_sockets:
        try:
            sock.close()
        except:
            pass
    
    udp_sockets = []
    
    # Crea nuovi socket
    for dest_host, dest_port in config["destinations"]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_sockets.append((sock, dest_host, dest_port))
            print(f"Socket UDP inizializzato per {dest_host}:{dest_port}")
        except Exception as e:
            print(f"Errore creazione socket UDP per {dest_host}:{dest_port}: {e}")

def send_gps_data(gps_data):
    """Invia i dati GPS a tutte le destinazioni."""
    global udp_sockets
    
    if not udp_sockets:
        init_udp_sockets()
        if not udp_sockets:
            return
    
    data_bytes = gps_data.encode()
    failed_sockets = []
    
    for i, (sock, dest_host, dest_port) in enumerate(udp_sockets):
        try:
            sock.sendto(data_bytes, (dest_host, dest_port))
        except Exception as e:
            print(f"Errore invio a {dest_host}:{dest_port} - {e}")
            failed_sockets.append(i)
    
    # Ricrea i socket che hanno fallito
    for i in failed_sockets:
        try:
            sock, dest_host, dest_port = udp_sockets[i]
            sock.close()
            new_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_sockets[i] = (new_sock, dest_host, dest_port)
        except Exception as e:
            print(f"Errore ricreazione socket: {e}")

def ntrip_worker():
    """Thread per la connessione al caster NTRIP."""
    global rtcm_data
    
    while running:
        try:
            print(f"Connessione al caster NTRIP {config['ntrip_host']}:{config['ntrip_port']}...")
            
            # Prepara credenziali
            credentials = f"{config['ntrip_username']}:{config['ntrip_password']}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            # Prepara richiesta HTTP
            request = (
                f"GET /{config['ntrip_mountpoint']} HTTP/1.1\r\n"
                f"User-Agent: NTRIP PythonClient/1.0\r\n"
                f"Authorization: Basic {encoded_credentials}\r\n"
                f"Ntrip-Version: NTRIP/2.0\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            )
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10.0)  # Timeout per la connessione
                s.connect((config["ntrip_host"], config["ntrip_port"]))
                s.sendall(request.encode())
                
                response = s.recv(1024)
                if b"ICY 200 OK" not in response:
                    print(f"Risposta NTRIP non valida")
                    raise ConnectionError("Risposta NTRIP non valida")
                
                print("Connessione NTRIP stabilita")
                s.settimeout(30.0)  # Timeout più lungo per la lettura
                
                # Salva i dati dopo l'header
                rtcm_part = response.split(b"\r\n\r\n", 1)
                if len(rtcm_part) > 1 and rtcm_part[1]:
                    with rtcm_lock:
                        rtcm_data = rtcm_part[1]
                
                # Loop di ricezione
                while running:
                    data = s.recv(1024)
                    if not data:
                        print("Connessione NTRIP chiusa dal server")
                        break
                    
                    with rtcm_lock:
                        rtcm_data = data
        
        except (socket.error, ConnectionError) as e:
            print(f"Errore NTRIP: {e}")
        except Exception as e:
            print(f"Errore imprevisto NTRIP: {e}")
        
        if running:
            print(f"Tentativo di riconnessione NTRIP tra {config['ntrip_retry']} secondi...")
            time.sleep(config["ntrip_retry"])

def gps_worker():
    """Thread per la connessione al GPS e l'elaborazione dei dati."""
    global gps_position, last_rtcm_time
    
    while running:
        ser = None
        try:
            print(f"Connessione al GPS sulla porta {config['gps_port']}...")
            ser = serial.Serial(config["gps_port"], config["gps_baudrate"], timeout=1)
            print("Connessione GPS stabilita")
            
            while running:
                try:
                    line = ser.readline().decode('ascii', errors='replace').strip()
                    
                    if not line or not line.startswith('$'):
                        continue
                    
                    # Aggiorna timestamp per calcolo hertz
                    with hertz_lock:
                        gps_update_times.append(time.time())
                    
                    # Invia tutti i dati NMEA
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
                                    'raw': line
                                }
                            
                            # Invia correzioni RTCM
                            current_time = time.time()
                            with rtcm_lock:
                                if rtcm_data and (current_time - last_rtcm_time) >= config["rtcm_interval"]:
                                    try:
                                        ser.write(rtcm_data)
                                        last_rtcm_time = current_time
                                    except Exception as e:
                                        print(f"Errore nell'invio correzioni RTCM: {e}")
                                        raise  # Forza la riconnessione
                    
                    except pynmea2.ParseError:
                        # Ignora errori di parsing
                        pass
                
                except serial.SerialException as e:
                    print(f"Errore seriale: {e}")
                    break
                except Exception as e:
                    print(f"Errore nella lettura GPS: {e}")
        
        except serial.SerialException as e:
            print(f"Errore apertura porta seriale {config['gps_port']}: {e}")
        except Exception as e:
            print(f"Errore imprevisto GPS: {e}")
        finally:
            if ser:
                try:
                    ser.close()
                except:
                    pass
        
        if running:
            print(f"Tentativo di riconnessione GPS tra {config['gps_retry']} secondi...")
            time.sleep(config["gps_retry"])

def hertz_worker():
    """Thread per il calcolo della frequenza di aggiornamento."""
    global current_hertz
    
    while running:
        try:
            time.sleep(1)
            
            with hertz_lock:
                now = time.time()
                # Rimuovi i timestamp più vecchi di 1 secondo
                while gps_update_times and now - gps_update_times[0] > 1.0:
                    gps_update_times.popleft()
                
                # Il numero di aggiornamenti nell'ultimo secondo è la frequenza in Hz
                current_hertz = len(gps_update_times) / 3
        except Exception as e:
            print(f"Errore nel calcolo hertz: {e}")

def status_worker():
    """Thread per la visualizzazione dello stato."""
    quality_map = {
        0: "Invalida",
        1: "GPS",
        2: "DGPS",
        4: "RTK fix",
        5: "RTK float",
        6: "DR"
    }
    
    while running:
        try:
            time.sleep(1)
            with gps_lock:
                if gps_position:
                    quality = gps_position['quality']
                    quality_desc = quality_map.get(quality, f"Sconosciuta ({quality})")
                    
                    print(f"Posizione: Lat: {gps_position['lat']:.6f}, "
                          f"Lon: {gps_position['lon']:.6f}, "
                          f"Qualità: {quality_desc}, "
                          f"Sat: {gps_position['satellites']}, "
                          f"Hz: {current_hertz:.1f}")
        except Exception as e:
            print(f"Errore visualizzazione stato: {e}")

def parse_arguments():
    """Funzione per gestire i parametri da linea di comando."""
    parser = argparse.ArgumentParser(description='Sistema GPS-RTK con correzioni NTRIP')
    
    parser.add_argument('--gps-port', dest='gps_port',
                      help='Porta seriale del ricevitore GPS')
    
    parser.add_argument('--ntrip-host', dest='ntrip_host',
                      help='Host del caster NTRIP')
    
    parser.add_argument('--ntrip-port', dest='ntrip_port', type=int,
                      help='Porta del caster NTRIP')
    
    parser.add_argument('--add-dest', dest='add_dest', action='append', 
                      help='Aggiungi destinazione nel formato host:porta')
    
    parser.add_argument('--clear-dest', dest='clear_dest', action='store_true',
                      help='Rimuovi tutte le destinazioni predefinite')
    
    return parser.parse_args()

def main():
    """Funzione principale."""
    global config
    
    # Parsing dei parametri da linea di comando
    args = parse_arguments()
    
    # Aggiorna la configurazione
    if args.gps_port:
        config["gps_port"] = args.gps_port
    
    if args.ntrip_host:
        config["ntrip_host"] = args.ntrip_host
    
    if args.ntrip_port:
        config["ntrip_port"] = args.ntrip_port
    
    # Gestione delle destinazioni
    if args.clear_dest:
        config["destinations"] = []
    
    if args.add_dest:
        for dest_str in args.add_dest:
            try:
                host, port = dest_str.split(':')
                config["destinations"].append((host, int(port)))
                print(f"Aggiunta destinazione: {host}:{port}")
            except ValueError:
                print(f"Formato destinazione non valido: {dest_str}. Usa host:porta")
    
    # Stampa la configurazione
    print("\nConfigurazione:")
    print(f"GPS: {config['gps_port']} ({config['gps_baudrate']} baud)")
    print(f"NTRIP: {config['ntrip_host']}:{config['ntrip_port']}/{config['ntrip_mountpoint']}")
    print("Destinazioni:")
    for dest_host, dest_port in config["destinations"]:
        print(f"  {dest_host}:{dest_port}")
    
    # Inizializza i socket UDP
    init_udp_sockets()
    
    # Avvia i thread
    threads = []
    
    ntrip_thread = threading.Thread(target=ntrip_worker)
    gps_thread = threading.Thread(target=gps_worker)
    hertz_thread = threading.Thread(target=hertz_worker)
    status_thread = threading.Thread(target=status_worker)
    
    ntrip_thread.daemon = True
    gps_thread.daemon = True
    hertz_thread.daemon = True
    status_thread.daemon = True
    
    threads.extend([ntrip_thread, gps_thread, hertz_thread, status_thread])
    
    for thread in threads:
        thread.start()
    
    print("Sistema GPS-RTK avviato. Premi Ctrl+C per terminare.")
    
    try:
        # Mantieni il programma in esecuzione
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nChiusura in corso...")
        global running
        running = False
        time.sleep(1)  # Attendi che i thread si fermino
        
        # Chiudi i socket
        for sock, _, _ in udp_sockets:
            try:
                sock.close()
            except:
                pass
        
        print("Sistema terminato.")

if __name__ == "__main__":
    main()
