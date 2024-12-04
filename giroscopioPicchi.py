import os
import time
import socket
import collections
import smbus
import subprocess
import threading
import wave
from flask import Flask, request, jsonify
import sounddevice as sd
import numpy as np  # For data processing


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

# Flask app setup
app = Flask(__name__)

# Global variables for audio
is_active = False
audio_thread = None
filename = "output.wav"  # Audio recording file
input_device = None  # Set to your USB microphone device index
output_device = None  # Set to your headphones' device index
sample_rate = 44100
channels = 1
file_lock = threading.Lock()
# Gain factors (90% gain = 0.9 multiplier)
MIC_GAIN = 0.9
OUTPUT_VOLUME = 0.9


# Audio monitoring and recording function
def record_and_play():
    global is_active
    print("Recording and pass-through started...")

    # Open WAV file for writing
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit audio = 2 bytes per sample
        wf.setframerate(sample_rate)

        # Open an audio stream
        with sd.Stream(device=(input_device, output_device),
                       samplerate=sample_rate,
                       channels=channels,
                       dtype="float32") as stream:
            while is_active:
                data, _ = stream.read(1024)  # Read audio from the microphone
		  # Apply microphone gain (scale input signal)
                mic_data = data * MIC_GAIN
                # Scale output volume
                out_data = mic_data * OUTPUT_VOLUME

                stream.write(data)          # Play it through the headphones

                # Write the audio data to the file
                with file_lock:
                    wf.writeframes((data * 32767).astype("int16").tobytes())  # Convert float32 to int16

    print("Recording and pass-through stopped.")

@app.route("/audio", methods=["POST"])
def control_audio():
    global is_active, audio_thread

    action = request.json.get("action")
    if action == "start":
        if is_active:
            return jsonify({"status": "error", "message": "Already active"}), 400

        is_active = True
        audio_thread = threading.Thread(target=record_and_play, daemon=True)
        audio_thread.start()
        return jsonify({"status": "success", "message": "Started recording and monitoring"})

    elif action == "stop":
        if not is_active:
            return jsonify({"status": "error", "message": "Not currently active"}), 400

        is_active = False
        audio_thread.join()  # Wait for the thread to finish
        return jsonify({"status": "success", "message": "Stopped recording and monitoring"})

    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400


# Sensor functions
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
    """Rileva un passo se l'attuale valore e un picco rispetto alla media precedente e successiva e supera la soglia di picco."""
    if current_value > average_past and current_value > average_future and current_value > PEAK_THRESHOLD:
        if (current_time - last_step_time) > STEP_INTERVAL:
            return True
    return False

# Initialize MPU6050
bus = smbus.SMBus(1)
bus.write_byte_data(MPU6050_ADDR, PWR_MGMT_1, 0)
bus.write_byte_data(MPU6050_ADDR, ACCEL_CONFIG, 0x08)
bus.write_byte_data(MPU6050_ADDR, GYRO_CONFIG, 0x00)

# Initialize socket
sock = create_socket()

# Initialize queues for moving average
past_values = collections.deque(maxlen=WINDOW_SIZE)
future_values = collections.deque(maxlen=WINDOW_SIZE)

# Step counter
step_count = 0
start_time = time.time()
last_step_time = start_time

# Run the Flask server in a separate thread
flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000), daemon=True)
flask_thread.start()

try:
    while True:
        # Read accelerometer values
        accel_x = read_word(MPU6050_ADDR, ACCEL_XOUT_H)
        accel_y = read_word(MPU6050_ADDR, ACCEL_YOUT_H)
        accel_z = read_word(MPU6050_ADDR, ACCEL_ZOUT_H)
        
        # Read gyroscope values
        gyro_x = read_word(MPU6050_ADDR, GYRO_XOUT_H)
        gyro_y = read_word(MPU6050_ADDR, GYRO_YOUT_H)
        gyro_z = read_word(MPU6050_ADDR, GYRO_ZOUT_H)

        # Update past and future value queues
        if len(future_values) < WINDOW_SIZE:
            future_values.append(accel_z)
            continue
        else:
            past_values.append(future_values.popleft())
            future_values.append(accel_z)

        # Calculate moving averages
        average_past = calculate_moving_average(past_values)
        average_future = calculate_moving_average(future_values)

        # Detect step
        current_time = time.time()
        if detect_step(average_past, accel_z, average_future, last_step_time, current_time):
            step_count += 1
            last_step_time = current_time
        
        # Create data string
        data_str = f"SENSOR,{str(HEAD_ID)},{str(SENSOR_ID)},{accel_x},{accel_y},{accel_z},{gyro_x},{gyro_y},{gyro_z},{step_count}"
        try:
            # Send data via socket
            sock.sendto(data_str.encode('utf-8'), (HOST, PORT))
            print("+ " + data_str)
        except socket.error:
            print("- " + data_str)
            print("Errore di invio dati.")

        # Wait before reading again
        time.sleep(0.04)

except KeyboardInterrupt:
    print("Programma interrotto dall'utente")
except Exception as e:
    print(f"Errore: {e}")
finally:
    sock.close()
