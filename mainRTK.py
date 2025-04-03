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

# Destinazioni UDP
DESTINATIONS = [
    ('10.0.0.3', 3131),
    ('213.209.192.165', 5001)
]

# Variabili globali
rtcm_data = b''
rtcm_lock = threading.Lock()
gps_position = None
gps_lock = threading.Lock()
last_rtcm_time = 0
RTCM_MIN_INTERVAL = 1.0

gps_update_times = deque(maxlen=100)
hertz_lock = threading.Lock()
current_hertz = 0

udp_socket = None

def connect_to_ntrip():
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

def init_udp_socket():
    global udp_socket
    if udp_socket is None:
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            print("Socket UDP inizializzato correttamente.")
        except Exception as e:
            print(f"Errore nell'inizializzazione del socket UDP: {e}")

def send_gps_data(gps_data):
    global udp_socket
    if udp_socket is None:
        print("Socket UDP non inizializzato!")
        return

    for host, port in DESTINATIONS:
        try:
            udp_socket.sendto(gps_data.encode(), (host, port))
        except Exception as e:
            print(f"Errore nell'invio dei dati GPS a {host}:{port}: {e}")

def update_hertz():
    global current_hertz
    while True:
        time.sleep(1)
        with hertz_lock:
            now = time.time()
            while gps_update_times and now - gps_update_times[0] > 1.0:
                gps_update_times.popleft()
            current_hertz = len(gps_update_times) / 3
            print(f"Frequenza attuale: {current_hertz} Hz")

def connect_to_gps():
    global gps_position
    try:
        with serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1) as ser:
            print(f"Connessione al GPS sulla porta {GPS_PORT}...")
            while True:
                try:
                    line = ser.readline().decode('ascii', errors='replace').strip()
                    if line.startswith('$'):
                        with hertz_lock:
                            gps_update_times.append(time.time())
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
                                        'hertz': current_hertz
                                    }
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
    parser = argparse.ArgumentParser(description='Sistema GPS-RTK con correzioni NTRIP')
    parser.add_argument('--gps-port', dest='gps_port', default=GPS_PORT,
                        help=f'Porta seriale del ricevitore GPS (default: {GPS_PORT})')
    return parser.parse_args()

def main():
    args = parse_arguments()
    global GPS_PORT
    GPS_PORT = args.gps_port

    print(f"Utilizzando porta GPS: {GPS_PORT}")
    for host, port in DESTINATIONS:
        print(f"Inviando dati a: {host}:{port}")

    init_udp_socket()

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
            with gps_lock:
                if gps_position:
                    print(f"Posizione: Lat: {gps_position['lat']}, Lon: {gps_position['lon']}, "
                          f"Qualità: {gps_position['quality']}, Hz: {current_hertz}")
    except KeyboardInterrupt:
        print("\nProgramma terminato dall'utente")

if __name__ == "__main__":
    main()
