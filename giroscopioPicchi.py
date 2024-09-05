import os
import time
import socket
import collections
import smbus
import subprocess

# Id sensori e HEAD
HEAD_ID = 1
SENSOR_ID = 3

# Indirizzo I2C del MPU6050
MPU6050_ADDR = 0x68

# Registri del MPU6050
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B
ACCEL_YOUT_H = 0x3D
ACCEL_ZOUT_H = 0x3F
GYRO_XOUT_H = 0x43
GYRO_YOUT_H = 0x45
GYRO_ZOUT_H = 0x47

ACCEL_CONFIG = 0x1C
GYRO_CONFIG = 0x1B

# Indirizzo IP e porta del server a cui inviare i dati
HOST, PORT = '95.230.211.208', 4141

# Intervallo di tempo minimo tra due passi (in secondi)
STEP_INTERVAL = 0.2

# Finestra per il calcolo della media (numero di campioni)
WINDOW_SIZE = 5

# Soglia di picco per considerare un passo valido
PEAK_THRESHOLD = 5000

def create_socket():
    """Crea il socket UDP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return s

def read_word(sensor_address, reg_address):
    """Legge i dati a 16 bit da un registro."""
    high = bus.read_byte_data(sensor_address, reg_address)
    low = bus.read_byte_data(sensor_address, reg_address + 1)
    value = (high << 8) + low
    if value >= 0x8000:
        value = -((65535 - value) + 1)
    return value

def calculate_moving_average(values):
    """Calcola la media mobile dei valori."""
    return sum(values) / len(values)

def detect_step(average_past, current_value, average_future, last_step_time, current_time):
    """Rileva un passo se l'attuale valore è un picco rispetto alla media precedente e successiva e supera la soglia di picco."""
    if current_value > average_past and current_value > average_future and current_value > PEAK_THRESHOLD:
        if (current_time - last_step_time) > STEP_INTERVAL:
            return True
    return False

# Inizializza il bus I2C
bus = smbus.SMBus(1)

# Risveglia il MPU6050 dal modo di sleep
bus.write_byte_data(MPU6050_ADDR, PWR_MGMT_1, 0)
bus.write_byte_data(MPU6050_ADDR, ACCEL_CONFIG, 0x08)
bus.write_byte_data(MPU6050_ADDR, GYRO_CONFIG, 0x00)

# Avvia il collegamento
sock = create_socket()

# Inizializza le code per la media mobile
past_values = collections.deque(maxlen=WINDOW_SIZE)
future_values = collections.deque(maxlen=WINDOW_SIZE)

# Contatore di passi
step_count = 0
start_time = time.time()
last_step_time = start_time

try:
    while True:
        # Leggi i valori dell'accelerometro
        accel_x = read_word(MPU6050_ADDR, ACCEL_XOUT_H)
        accel_y = read_word(MPU6050_ADDR, ACCEL_YOUT_H)
        accel_z = read_word(MPU6050_ADDR, ACCEL_ZOUT_H)
        
        # Leggi i valori giroscopio
        gyro_x = read_word(MPU6050_ADDR, GYRO_XOUT_H)
        gyro_y = read_word(MPU6050_ADDR, GYRO_YOUT_H)
        gyro_z = read_word(MPU6050_ADDR, GYRO_ZOUT_H)

        # Aggiorna la coda dei valori passati e futuri
        if len(future_values) < WINDOW_SIZE:
            future_values.append(accel_z)
            continue
        else:
            past_values.append(future_values.popleft())
            future_values.append(accel_z)

        # Calcola le medie mobili
        average_past = calculate_moving_average(past_values)
        average_future = calculate_moving_average(future_values)

        # Rileva un passo
        current_time = time.time()
        if detect_step(average_past, accel_z, average_future, last_step_time, current_time):
            step_count += 1
            last_step_time = current_time
        
        # Crea la stringa dei dati
        data_str = f"SENSOR,{str(HEAD_ID)},{str(SENSOR_ID)},{accel_x},{accel_y},{accel_z},{gyro_x},{gyro_y},{gyro_z},{step_count}"
        try:
            # Invia i dati come stringa al server attraverso il socket UDP
            sock.sendto(data_str.encode('utf-8'), (HOST, PORT))
            print("+ " + data_str)
        except socket.error:
            print("- " + data_str)
            print("Errore di invio dati.")

        # Attendere 40 millisecondi prima di leggere nuovamente
        time.sleep(0.04)

except KeyboardInterrupt:
    print("Programma interrotto dall'utente")
except Exception as e:
    print(f"Errore: {e}")
finally:
    # Chiudi il socket al termine dell'invio
    sock.close()
