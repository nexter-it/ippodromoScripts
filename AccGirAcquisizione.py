#!/usr/bin/env python3
"""
Script per Raspberry Pi Zero con RaspbianOS:
Legge i dati da un sensore giroscopio/accelerometro (es. MPU6050) 15 volte al secondo
e li salva ogni 15 secondi in un file CSV (sensor_log.csv).
"""

import time
import csv
import os
from mpu6050 import mpu6050

# Inizializza il sensore (assicurati che l'indirizzo I2C sia corretto, di default 0x68)
sensor = mpu6050(0x68)

# File di log (CSV)
log_file = "sensor_log.csv"

# Se il file non esiste, crea il file e scrivi l'intestazione
if not os.path.exists(log_file):
    with open(log_file, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["timestamp", "accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z"])

# Parametri: frequenza di lettura e intervallo di salvataggio
read_frequency = 15           # letture al secondo
read_interval = 1.0 / read_frequency  # intervallo in secondi (~0.0667 s)
log_interval = 15             # salva ogni 15 secondi

accumulated_data = []
last_save_time = time.time()

#print("Inizio acquisizione dati. Premi CTRL+C per terminare.")

try:
    while True:
        current_time = time.time()
        # Leggi i dati accelerometro e giroscopio
        accel = sensor.get_accel_data()
        gyro = sensor.get_gyro_data()

        # Prepara il record con il timestamp (in secondi dall'epoca) e i dati letti
        record = [
            current_time,
            accel["x"], accel["y"], accel["z"],
            gyro["x"], gyro["y"], gyro["z"]
        ]
        accumulated_data.append(record)

        # Ogni 15 secondi, scrivi i dati accumulati nel file CSV e svuota la lista
        if current_time - last_save_time >= log_interval:
            with open(log_file, "a", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerows(accumulated_data)
            print(f"Salvati {len(accumulated_data)} record nel file {log_file}")
            accumulated_data = []  # resetta la lista dei dati
            last_save_time = current_time

        # Attende per mantenere la frequenza di 15 letture al secondo
        time.sleep(read_interval)

except KeyboardInterrupt:
    print("Terminazione del programma. Salvataggio dati residui...")
    # Se ci sono dati non salvati, li scrive al termine
    if accumulated_data:
        with open(log_file, "a", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerows(accumulated_data)
    print("Dati salvati. Uscita.")
