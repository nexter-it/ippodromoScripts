import subprocess
import gpsd
import time
import socket
import math
import json
import psutil
from filterpy.kalman import KalmanFilter
import numpy as np

KALMAN_FLAG = false
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
initial_measurements = 5  # Number of initial measurements to average for dt

# --- Kalman Filter Setup ---
dt = 0.04  # Initial guess, will be updated
kf = KalmanFilter(dim_x=4, dim_z=2)  # State is 4D (x, y, vx, vy), Measurement is 2D (x, y)

# State Transition Matrix (Process Model - Constant Velocity)
kf.F = np.array([[1, 0, dt, 0],
                 [0, 1, 0, dt],
                 [0, 0, 1, 0],
                 [0, 0, 0, 1]])

# Measurement Function (Measurement Model - Position Measurement)
kf.H = np.array([[1, 0, 0, 0],
                 [0, 1, 0, 0]])

# Process Noise Covariance Matrix (Q) - Tune these values
kf.Q = np.eye(4) * 0.1  # Example: small process noise

# Measurement Noise Covariance Matrix (R) - Tune based on GPS accuracy (hAcc)
kf.R = np.eye(2) * 1.0  # Example: Measurement noise with std dev of 1 meter

# Initial State Estimate (x) - Initial position and velocity (can be zero or initial GPS reading)
kf.x = np.array([0., 0., 0., 0.])  # Initial state: [x, y, vx, vy] = [0, 0, 0, 0]

# Initial State Covariance Matrix (P) - Initial uncertainty in state (start with high uncertainty)
kf.P *= 1000.  # Large initial covariance
# --- End Kalman Filter Setup ---

# Connessione al demone gpsd
gpsd.connect()

# Avvia il collegamento
sock = create_socket()

last_positions = []
packet_count = 0
last_time = time.time()

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
             
                z = np.array([packet.lon, packet.lat])  # Measurement vector (lon, lat)
                kf.update(z)

                # --- Get Filtered State ---
                filtered_state = kf.x
                filtered_lon = filtered_state[0] if KALMAN_FLAG else packet.lon
                filtered_lat = filtered_state[1] if KALMAN_FLAG else packet.lat

             
                # Aggiungi la posizione attuale alla lista delle ultime posizioni
                last_positions.append((filtered_lat, filtered_lon))
                # Mantieni solo le ultime 3 posizioni
                if len(last_positions) > 6:
                    last_positions.pop(0)

                # Calcola la direzione solo tra la prima e l'ultima posizione
                if len(last_positions) > 1:
                    lat1, lon1 = last_positions[0]  # Prima posizione
                    lat2, lon2 = last_positions[-1] # Ultima posizione
                    average_bearing = calculate_bearing(lat1, lon1, lat2, lon2)
                else:
                    average_bearing = "N/A"

                    
                packet_count += 1
                # Legge il consumo di CPU e di RAM
                cpu_usage = psutil.cpu_percent()
                ram_usage = psutil.virtual_memory().percent
                
                data = [
                    "GPS",
                    str(HEAD_ID),
                    str(filtered_lat),  # Latitudine
                    str(filtered_lon),  # Longitudine
                    str(packet.get_time()),  # Orario
                    str(packet.alt) if packet.alt is not None else 'N/A',  # Altitudine
                    str(packet.hspeed),  # Velocità orizzontale
                    str(int(average_bearing)),
                    str(cpu_usage),  # Uso della CPU in percentuale
                    str(ram_usage)   # Uso della RAM in percentuale
                ]
                
                # Unisce gli elementi dell'array in una stringa separata da virgole
                data_str = ','.join(data)
                try:
                    # Invia i dati come stringa al server attraverso il socket UDP
                    sock.sendto(data_str.encode('utf-8'), (HOST, PORT))
                    print("[ " + str(packet_count) + " ]" + " + " + data_str)
                except socket.error:
                    print("[ " + str(packet_count) + " ]" + " - " + data_str)
                    print("Errore di invio dati.")
                last_time = current_time
            try:
                speed = float(packet.hspeed)
            except (TypeError, ValueError):
                speed = 0
            
            speed = speed * 3.6

            #if speed <= 2:
            #    time.sleep(1)      # 1 pacchetto al secondo
            #else:
            time.sleep(0.04)   # 25 pacchetti al secondo
        except Exception as e:
            if "GPS not active" in str(e):
                print("Errore GPS: GPS non attivo, attesa di 10 secondi.")
                time.sleep(10)  # Attende 10 secondi prima di riprovare
            else:
                print(f"Errore non gestito: {e}")

except KeyboardInterrupt:
    print("Programma interrotto dall'utente")
except Exception as e:
    print(f"Errore: {e}")
finally:
    # Chiudi il socket al termine dell'invio
    sock.close()
