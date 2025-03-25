import subprocess
import gpsd
import time
import socket
import math
import json
import psutil
from filterpy.kalman import KalmanFilter
import numpy as np
import os
from datetime import datetime

# Flag per l'utilizzo del filtro Kalman
KALMAN_FLAG = False

# Indirizzo IP e porta del server a cui inviare i dati
#HOST, PORT = '95.230.211.208', 4141
HOST, PORT = '95.230.211.208', 4141

# ID HEAD DEFAULT
HEAD_ID = 999

try:
    with open('/home/pi/config.json', 'r') as config_file:
        config = json.load(config_file)
    HEAD_ID = config.get("HEAD_ID", 6)
except Exception as e:
    print(f"Errore nella lettura del file di configurazione: {e}")
    HEAD_ID = 999
    
print("HEAD_ID settata:" + str(HEAD_ID))
    
def create_socket():
    """ Crea il socket UDP. """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return s

# Calcola la direzione tra due coordinate
def calculate_bearing(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dLon = lon2 - lon1
    x = math.sin(dLon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(dLon))
    initial_bearing = math.atan2(x, y)
    initial_bearing = math.degrees(initial_bearing)
    bearing = (initial_bearing + 360) % 360
    return bearing

last_time = time.time()
interval_sum = 0
position_count = 0
initial_measurements = 5  # Numero di misurazioni iniziali per calcolare dt

# --- Kalman Filter Setup ---
dt = 0.04  # Stima iniziale, verrà aggiornata
kf = KalmanFilter(dim_x=4, dim_z=2)  # Stato 4D (x, y, vx, vy), Misura 2D (x, y)

# Matrice di transizione dello stato (modello a velocità costante)
kf.F = np.array([[1, 0, dt, 0],
                 [0, 1, 0, dt],
                 [0, 0, 1, 0],
                 [0, 0, 0, 1]])

# Funzione di misura (misurazione della posizione)
kf.H = np.array([[1, 0, 0, 0],
                 [0, 1, 0, 0]])

# Matrice di covarianza del rumore di processo (Q) - da regolare
kf.Q = np.eye(4) * 0.1  # Esempio: rumore di processo ridotto

# Matrice di covarianza del rumore di misura (R) - da regolare in base all'accuratezza del GPS (hAcc)
kf.R = np.eye(2) * 1.0  # Esempio: rumore di misura con deviazione standard di 1 metro

# Stato iniziale (x) - posizione e velocità iniziali (0 o lettura GPS iniziale)
kf.x = np.array([0., 0., 0., 0.])

# Matrice di covarianza iniziale (P) - incertezza elevata all'inizio
kf.P *= 1000.
# --- Fine Setup Kalman Filter ---

# Connessione al demone gpsd
gpsd.connect()

# Creazione del socket UDP
sock = create_socket()

last_positions = []
packet_count = 0
last_time = time.time()

# --- Setup Logging ---
log_dir = "/home/pi/ippodromoScripts/logGNSS"
os.makedirs(log_dir, exist_ok=True)
log_buffer = []  # Buffer per accumulare le righe da salvare
last_log_time = time.time()  # Tempo dell'ultimo salvataggio

try:
    while True:
        current_time = time.time()
        if current_time - last_time >= 1:
            packet_count = 0
            last_time = current_time

        try:
            packet = gpsd.get_current()
            if packet.mode >= 2:
                interval = current_time - last_time
                interval_sum += interval
                position_count += 1
                average_interval = interval_sum / position_count if position_count > 0 else 0
        
                if position_count <= initial_measurements:
                    if position_count == initial_measurements:
                        dt = average_interval
                        kf.F = np.array([[1, 0, dt, 0],
                                         [0, 1, 0, dt],
                                         [0, 0, 1, 0],
                                         [0, 0, 0, 1]])
                        print(f"Kalman dt updated to: {dt:.4f}s")
                kf.predict()
             
                z = np.array([packet.lon, packet.lat])  # Vettore di misura (lon, lat)
                kf.update(z)

                # --- Stato filtrato ---
                filtered_state = kf.x
                filtered_lon = filtered_state[0] if KALMAN_FLAG else packet.lon
                filtered_lat = filtered_state[1] if KALMAN_FLAG else packet.lat

                # Aggiorna la lista delle ultime posizioni
                last_positions.append((filtered_lat, filtered_lon))
                if len(last_positions) > 6:
                    last_positions.pop(0)

                # Calcola la direzione tra la prima e l'ultima posizione
                if len(last_positions) > 1:
                    lat1, lon1 = last_positions[0]
                    lat2, lon2 = last_positions[-1]
                    average_bearing = calculate_bearing(lat1, lon1, lat2, lon2)
                else:
                    average_bearing = "N/A"
                    
                packet_count += 1

                # Legge il consumo di CPU e RAM
                cpu_usage = psutil.cpu_percent()
                ram_usage = psutil.virtual_memory().percent
                
                data = [
                    "GPS",
                    str(HEAD_ID),
                    str(filtered_lat),      # Latitudine
                    str(filtered_lon),      # Longitudine
                    str(packet.get_time()), # Orario
                    str(packet.alt) if packet.alt is not None else 'N/A',  # Altitudine
                    str(packet.hspeed),     # Velocità orizzontale
                    str(int(average_bearing)),
                    str(cpu_usage),         # Uso della CPU (%)
                    str(ram_usage)          # Uso della RAM (%)
                ]
                
                # Unisce gli elementi in una stringa separata da virgole
                data_str = ','.join(data)
                
                try:
                    # Invio dei dati via socket UDP
                    sock.sendto(data_str.encode('utf-8'), (HOST, PORT))
                    print("[ " + str(packet_count) + " ]" + " + " + data_str)
                except socket.error:
                    print("[ " + str(packet_count) + " ]" + " - " + data_str)
                    print("Errore di invio dati.")
                
                # Aggiunge la riga al buffer di log
                log_buffer.append(data_str)
                
                # Controlla se sono passati 15 secondi per salvare il log
                if current_time - last_log_time >= 15:
                    filename = datetime.now().strftime("%Y%m%d_%H.log")
                    file_path = os.path.join(log_dir, filename)
                    with open(file_path, 'a') as f:
                        for line in log_buffer:
                            f.write(line + "\n")
                    log_buffer = []  # Svuota il buffer
                    last_log_time = current_time

                last_time = current_time
            try:
                speed = float(packet.hspeed)
            except (TypeError, ValueError):
                speed = 0
            
            speed = speed * 3.6  # Conversione da m/s a km/h

            # Se la velocità è bassa, si potrebbe rallentare il ciclo (qui commentato)
            # if speed <= 2:
            #    time.sleep(1)      # 1 pacchetto al secondo
            # else:
            time.sleep(0.04)   # 25 pacchetti al secondo
        except Exception as e:
            if "GPS not active" in str(e):
                print("Errore GPS: GPS non attivo, attesa di 10 secondi.")
                time.sleep(10)  # Attesa di 10 secondi prima del prossimo tentativo
            else:
                print(f"Errore non gestito: {e}")

except KeyboardInterrupt:
    print("Programma interrotto dall'utente")
except Exception as e:
    print(f"Errore: {e}")
finally:
    # Chiusura del socket UDP
    sock.close()
