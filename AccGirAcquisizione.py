#!/usr/bin/env python3
"""
Script per Raspberry Pi Zero con RaspbianOS:
Legge i dati da un sensore giroscopio/accelerometro (es. MPU6050) 15 volte al secondo
e li salva ogni 15 secondi in un file CSV. Viene creato un nuovo file ogni ora
con nome che include la data e l'ora.
"""

import time
import csv
import os
from datetime import datetime
from mpu6050 import mpu6050

# Inizializza il sensore (assicurati che l'indirizzo I2C sia corretto, di default 0x68)
sensor = mpu6050(0x68)

# Directory in cui salvare i file di log
log_dir = "/home/pi/ippodromoScripts/logAccGir"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Funzione per ottenere il nome del file in base all'ora corrente
def get_log_filename():
    # Il nome del file avrà il formato: sensor_log_YYYYMMDD_HH.csv
    return os.path.join(log_dir, f"sensor_log_{datetime.now().strftime('%Y%m%d_%H')}.csv")

# Funzione per scrivere i dati accumulati in un file CSV
def flush_data(accumulated_data, filename):
    # Se il file non esiste, scrive l'intestazione
    write_header = not os.path.exists(filename)
    with open(filename, "a", newline="") as csvfile:
        writer = csv.writer(csvfile)
        if write_header:
            # Aggiunta della colonna "timestamp_ms" per il timestamp formattato al millisecondo
            writer.writerow(["timestamp", "timestamp_ms", "accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z"])
        writer.writerows(accumulated_data)

# Parametri: frequenza di lettura e intervallo di salvataggio
read_frequency = 15           # 15 letture al secondo
read_interval = 1.0 / read_frequency  # intervallo (~0.0667 s)
log_interval = 15             # salva ogni 15 secondi

accumulated_data = []
last_save_time = time.time()
current_log_file = get_log_filename()

print("Inizio acquisizione dati. Premi CTRL+C per terminare.")

try:
    while True:
        # Ottieni il timestamp come float (secondi dall'epoca)
        current_time = time.time()
        # Ottieni anche un timestamp formattato con millisecondi
        timestamp_ms = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        # Leggi i dati accelerometro e giroscopio
        accel = sensor.get_accel_data()
        gyro = sensor.get_gyro_data()

        # Prepara il record: timestamp float, timestamp formattato, e dati letti
        record = [
            current_time,
            timestamp_ms,
            accel["x"], accel["y"], accel["z"],
            gyro["x"], gyro["y"], gyro["z"]
        ]
        accumulated_data.append(record)

        # Se è arrivato il momento di salvare
        if current_time - last_save_time >= log_interval:
            # Aggiorna il nome del file in base all'ora corrente
            new_log_file = get_log_filename()
            if new_log_file != current_log_file:
                current_log_file = new_log_file
            flush_data(accumulated_data, current_log_file)
            print(f"Salvati {len(accumulated_data)} record in {current_log_file}")
            accumulated_data = []  # resetta la lista dei dati
            last_save_time = current_time

        # Attende per mantenere la frequenza di 15 letture al secondo
        time.sleep(read_interval)

except KeyboardInterrupt:
    print("Terminazione del programma. Salvataggio dati residui...")
    if accumulated_data:
        # Aggiorna il nome del file per l'ultimo flush
        current_log_file = get_log_filename()
        flush_data(accumulated_data, current_log_file)
    print("Dati salvati. Uscita.")
