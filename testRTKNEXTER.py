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

last_speed_kmh   = 0.0
last_timestamp   = "000101000000"
last_print_ts    = 0.0    # ← per limitare la stampa a 1 Hz
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
# --------------------------------------------------------------------

# ───────────────────────── THREAD - GPS ─────────────────────────────
def gps_worker():
    """Legge la seriale GPS, estrae dati da RMC/GGA e invia pacchetti."""
    global last_speed_kmh, last_timestamp, last_print_ts

    print(f"[GPS] seriale {CONFIG['gps_port']} @ {CONFIG['gps_baud']}")
    while running:
        try:
            with serial.Serial(CONFIG["gps_port"], CONFIG["gps_baud"], timeout=1) as ser:
                for raw in ser:
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

                    # ------------------- RMC -------------------
                    if isinstance(msg, pynmea2.RMC):
                        # velocità (knots → km/h)
                        try:
                            speed_kmh = float(msg.spd_over_grnd or 0.0) * 1.852
                        except ValueError:
                            speed_kmh = 0.0
                        last_speed_kmh = speed_kmh

                        # timestamp UTC
                        if msg.datestamp and msg.datetime:
                            dt = datetime.datetime.combine(msg.datestamp, msg.datetime.time())
                        elif msg.datestamp and msg.timestamp:
                            dt = datetime.datetime.combine(msg.datestamp, msg.timestamp)
                        else:
                            dt = datetime.datetime.utcnow()
                        last_timestamp = dt.strftime("%y%m%d%H%M%S")

                    # ------------------- GGA -------------------
                    elif isinstance(msg, pynmea2.GGA) and msg.gps_qual > 0:
                        compact = (
                            f"{MAC_ADDR}/"
                            f"{msg.latitude:+09.7f}/"
                            f"{msg.longitude:+010.7f}/"
                            f"{int(msg.num_sats):02d}/"
                            f"{int(msg.gps_qual)}/"
                            f"{last_speed_kmh:.1f}/"
                            f"{last_timestamp}\n"
                        )

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
