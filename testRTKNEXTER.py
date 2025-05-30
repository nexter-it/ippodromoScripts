#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Invia una singola riga compatta con i dati RTK/GNSS
su tutte le destinazioni UDP configurate e ne stampa
una al secondo sul terminale.

Formato pacchetto:
    MAC/±DD.dddddd7/±DDD.dddddd7/ss/q/vv.v/YYMMDDhhmmss
"""

import socket
import serial
import threading
import time
import base64
import datetime
import subprocess
import re

import pynmea2

# ────────────────────────── CONFIGURAZIONE ──────────────────────────
CONFIG = {
    "gps_port":     "/dev/ttyACM0",
    "gps_baud":     115200,
    "destinations": [("193.70.113.55", 3131)],

    # Parametri NTRIP (opzionale):
    "ntrip_host":   "83.217.185.132",
    "ntrip_port":   2101,
    "mount":        "NEXTER",
    "user":         "nexter",
    "password":     "nexter25",
}
# --------------------------------------------------------------------

def get_wlan0_mac():
    """Ottiene il MAC address dell'interfaccia wlan0."""
    try:
        # Metodo 1: usando /sys/class/net/wlan0/address
        with open('/sys/class/net/wlan0/address', 'r') as f:
            mac = f.read().strip().replace(':', '').upper()
            return mac
    except FileNotFoundError:
        pass
    
    try:
        # Metodo 2: usando il comando ip
        result = subprocess.run(['ip', 'link', 'show', 'wlan0'], 
                              capture_output=True, text=True, check=True)
        match = re.search(r'link/ether ([0-9a-f:]{17})', result.stdout)
        if match:
            mac = match.group(1).replace(':', '').upper()
            return mac
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    try:
        # Metodo 3: usando ifconfig (fallback)
        result = subprocess.run(['ifconfig', 'wlan0'], 
                              capture_output=True, text=True, check=True)
        match = re.search(r'ether ([0-9a-f:]{17})', result.stdout)
        if match:
            mac = match.group(1).replace(':', '').upper()
            return mac
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    # Fallback: usa uuid.getnode() se wlan0 non è disponibile
    import uuid
    print("[WARNING] wlan0 non trovata, uso MAC generico")
    return f"{uuid.getnode():012X}"

# MAC address dell'interfaccia wlan0
MAC_ADDR = get_wlan0_mac()
print(f"[INFO] MAC wlan0: {MAC_ADDR}")

# ───────────── variabili globali condivise fra i thread ─────────────
running          = True
udp_socks        = []

# Dati GPS più recenti
gps_data = {
    'speed_kmh': 0.0,
    'timestamp': datetime.datetime.utcnow().strftime("%y%m%d%H%M%S"),
    'latitude': None,
    'longitude': None,
    'satellites': 0,
    'quality': 0,
    'last_valid_time': None
}
gps_lock = threading.Lock()

last_print_ts = 0.0    # per limitare la stampa a 1 Hz
# --------------------------------------------------------------------

# ─────────────────────────── FUNZIONI UTILI ─────────────────────────
def init_udp():
    """Inizializza i socket UDP indicati in CONFIG."""
    global udp_socks
    for s, *_ in udp_socks:
        s.close()
    udp_socks.clear()
    for host, port in CONFIG["destinations"]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socks.append((sock, host, port))
        print(f"[UDP] destinazione {host}:{port}")


def send_udp(msg: str):
    """Invia msg a tutte le destinazioni UDP configurate."""
    data = msg.encode()
    for sock, host, port in udp_socks:
        try:
            sock.sendto(data, (host, port))
        except OSError as e:
            print(f"[!] UDP error {host}:{port} – {e}")


def update_timestamp_from_msg(msg):
    """Aggiorna il timestamp dai dati del messaggio NMEA."""
    current_time = None
    
    # Prima prova con datestamp + datetime (RMC)
    if hasattr(msg, 'datestamp') and hasattr(msg, 'datetime') and msg.datestamp and msg.datetime:
        try:
            current_time = datetime.datetime.combine(msg.datestamp, msg.datetime.time())
        except (AttributeError, ValueError):
            pass
    
    # Poi prova con datestamp + timestamp (RMC alternativo)
    if not current_time and hasattr(msg, 'datestamp') and hasattr(msg, 'timestamp') and msg.datestamp and msg.timestamp:
        try:
            current_time = datetime.datetime.combine(msg.datestamp, msg.timestamp)
        except (AttributeError, ValueError):
            pass
    
    # Infine prova solo con timestamp (GGA)
    if not current_time and hasattr(msg, 'timestamp') and msg.timestamp:
        try:
            # Per GGA, usa la data corrente con l'ora dal GPS
            today = datetime.date.today()
            current_time = datetime.datetime.combine(today, msg.timestamp)
        except (AttributeError, ValueError):
            pass
    
    # Se abbiamo un tempo valido, aggiornalo
    if current_time:
        with gps_lock:
            gps_data['timestamp'] = current_time.strftime("%y%m%d%H%M%S")
            gps_data['last_valid_time'] = current_time
        return True
    
    return False
# --------------------------------------------------------------------

# ───────────────────────── THREAD - GPS ─────────────────────────────
def gps_worker():
    """Legge la seriale GPS, estrae dati da RMC/GGA/VTG e invia pacchetti."""
    global last_print_ts

    print(f"[GPS] seriale {CONFIG['gps_port']} @ {CONFIG['gps_baud']}")
    while running:
        try:
            with serial.Serial(CONFIG["gps_port"], CONFIG["gps_baud"], timeout=1) as ser:
                for raw in ser:
                    if not running:
                        break
                        
                    try:
                        line = raw.decode("ascii", errors="replace").strip()
                    except UnicodeDecodeError:
                        continue
                    if not line.startswith('$'):
                        continue

                    # prova a parsare la sentenza NMEA
                    try:
                        msg = pynmea2.parse(line)
                    except pynmea2.ParseError:
                        continue

                    # ------------------- VTG -------------------
                    if isinstance(msg, pynmea2.VTG):
                        with gps_lock:
                            # Velocità diretta in km/h dal VTG
                            try:
                                if msg.spd_over_grnd_kmph is not None:
                                    gps_data['speed_kmh'] = float(msg.spd_over_grnd_kmph)
                                elif msg.spd_over_grnd_kts is not None:
                                    speed_knots = float(msg.spd_over_grnd_kts)
                                    gps_data['speed_kmh'] = speed_knots * 1.852
                                else:
                                    gps_data['speed_kmh'] = 0.0
                            except (ValueError, TypeError):
                                gps_data['speed_kmh'] = 0.0

                    # ------------------- RMC -------------------
                    elif isinstance(msg, pynmea2.RMC):
                        with gps_lock:
                            # Velocità (knots → km/h)
                            try:
                                if msg.spd_over_grnd is not None:
                                    gps_data['speed_kmh'] = float(msg.spd_over_grnd) * 1.852
                                else:
                                    gps_data['speed_kmh'] = 0.0
                            except (ValueError, TypeError):
                                gps_data['speed_kmh'] = 0.0
                            
                            # Posizione da RMC se valida
                            if msg.status == 'A' and msg.latitude and msg.longitude:  # 'A' = Active/Valid
                                gps_data['latitude'] = msg.latitude
                                gps_data['longitude'] = msg.longitude
                        
                        # Timestamp da RMC
                        update_timestamp_from_msg(msg)

                    # ------------------- GGA -------------------
                    elif isinstance(msg, pynmea2.GGA):
                        should_send = False
                        
                        with gps_lock:
                            # Aggiorna sempre satelliti e qualità
                            try:
                                gps_data['satellites'] = int(msg.num_sats) if msg.num_sats else 0
                            except (ValueError, TypeError):
                                gps_data['satellites'] = 0
                                
                            try:
                                gps_data['quality'] = int(msg.gps_qual) if msg.gps_qual else 0
                            except (ValueError, TypeError):
                                gps_data['quality'] = 0
                            
                            # Posizione da GGA se abbiamo un fix valido
                            if msg.gps_qual and int(msg.gps_qual) > 0 and msg.latitude and msg.longitude:
                                gps_data['latitude'] = msg.latitude
                                gps_data['longitude'] = msg.longitude
                                should_send = True
                            
                            # Crea il pacchetto se abbiamo posizione valida
                            if should_send and gps_data['latitude'] is not None and gps_data['longitude'] is not None:
                                compact = (
                                    f"{MAC_ADDR}/"
                                    f"{gps_data['latitude']:+09.7f}/"
                                    f"{gps_data['longitude']:+010.7f}/"
                                    f"{gps_data['satellites']:02d}/"
                                    f"{gps_data['quality']}/"
                                    f"{gps_data['speed_kmh']:.1f}/"
                                    f"{gps_data['timestamp']}\n"
                                )
                        
                        # Timestamp da GGA se non l'abbiamo già da RMC
                        update_timestamp_from_msg(msg)
                        
                        # Invia solo se abbiamo un fix valido
                        if should_send:
                            send_udp(compact)

                            # ---------- STAMPA max 1 riga al secondo ----------
                            now = time.time()
                            if now - last_print_ts >= 1.0:
                                print(compact.strip())
                                last_print_ts = now

        except serial.SerialException as e:
            print(f"[GPS] {e}; ritento in 3 s")
            time.sleep(3)
# --------------------------------------------------------------------

# ─────────────────────── THREAD - NTRIP (opz.) ──────────────────────
def ntrip_worker():
    """Riceve correzioni RTCM dal caster NTRIP e le inoltra alla seriale GPS."""
    while running:
        try:
            creds = base64.b64encode(f"{CONFIG['user']}:{CONFIG['password']}".encode()).decode()
            req = (f"GET /{CONFIG['mount']} HTTP/1.0\r\n"
                   f"User-Agent: NTRIP python\r\n"
                   f"Authorization: Basic {creds}\r\n\r\n")

            with socket.create_connection((CONFIG["ntrip_host"], CONFIG["ntrip_port"]), 10) as s:
                s.sendall(req.encode())
                if b"ICY 200 OK" not in s.recv(1024):
                    print("[NTRIP] risposta non valida")
                    raise ConnectionError
                print("[NTRIP] connesso")

                with serial.Serial(CONFIG["gps_port"], CONFIG["gps_baud"], timeout=1) as ser:
                    while running:
                        data = s.recv(1024)
                        if not data:
                            raise ConnectionError("stream chiuso")
                        ser.write(data)

        except Exception as e:
            print(f"[NTRIP] {e}; riconnessione in 5 s")
            time.sleep(5)
# --------------------------------------------------------------------

# ───────────────────────────── MAIN ────────────────────────────────
if __name__ == "__main__":
    init_udp()

    t_gps   = threading.Thread(target=gps_worker,   daemon=True)
    t_ntrip = threading.Thread(target=ntrip_worker, daemon=True)
    t_gps.start()
    t_ntrip.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        running = False
        print("\n[MAIN] interrompo…")
        for s, *_ in udp_socks:
            s.close()
