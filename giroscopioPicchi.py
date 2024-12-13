from datetime import datetime
import os
import time
import socket
import collections
import smbus
import threading
import wave
from flask import Flask, request, jsonify
import sounddevice as sd
import numpy as np
import subprocess

# Print available sound devices
print(sd.query_devices())

# IDs and constants
HEAD_ID = 1
SENSOR_ID = 3

# I2C address and MPU6050 registers
MPU6050_ADDR = 0x68
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B
ACCEL_YOUT_H = 0x3D
ACCEL_ZOUT_H = 0x3F
GYRO_XOUT_H = 0x43
GYRO_YOUT_H = 0x45
GYRO_ZOUT_H = 0x47
ACCEL_CONFIG = 0x1C
GYRO_CONFIG = 0x1B

# Server details
HOST, PORT = '95.230.211.208', 4141

# Step detection parameters
STEP_INTERVAL = 0.2
WINDOW_SIZE = 5
PEAK_THRESHOLD = 5000

# Flask app setup
app = Flask(__name__)

# Global variables
is_active = False
audio_thread = None
input_device = "hw:1,0"  # USB microphone
output_device = "hw:1,0"  # Headphones or speaker
sample_rate = 44100
channels = 1
MIC_GAIN = 0.9
OUTPUT_VOLUME = 0.9
file_lock = threading.Lock()

# Initialize MPU6050
bus = smbus.SMBus(1)
bus.write_byte_data(MPU6050_ADDR, PWR_MGMT_1, 0)
bus.write_byte_data(MPU6050_ADDR, ACCEL_CONFIG, 0x08)
bus.write_byte_data(MPU6050_ADDR, GYRO_CONFIG, 0x00)

# Socket and step detection setup
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
past_values = collections.deque(maxlen=WINDOW_SIZE)
future_values = collections.deque(maxlen=WINDOW_SIZE)
step_count = 0
last_step_time = time.time()


def read_word(sensor_address, reg_address):
    """Read 16-bit data from the sensor."""
    high = bus.read_byte_data(sensor_address, reg_address)
    low = bus.read_byte_data(sensor_address, reg_address + 1)
    value = (high << 8) + low
    if value >= 0x8000:
        value = -((65535 - value) + 1)
    return value


def calculate_moving_average(values):
    """Calculate the moving average of values."""
    return sum(values) / len(values)


def detect_step(average_past, current_value, average_future, last_step_time, current_time):
    """Detect a step based on peak threshold."""
    if current_value > average_past and current_value > average_future and current_value > PEAK_THRESHOLD:
        if (current_time - last_step_time) > STEP_INTERVAL:
            return True
    return False


def write_accel():
    """Write accelerometer and gyroscope data to a file."""
    global is_active, last_step_time, step_count
    filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"

    with open(filename, 'a') as file:
        try:
            while is_active:
                # Read accelerometer values
                accel_x = read_word(MPU6050_ADDR, ACCEL_XOUT_H)
                accel_y = read_word(MPU6050_ADDR, ACCEL_YOUT_H)
                accel_z = read_word(MPU6050_ADDR, ACCEL_ZOUT_H)

                # Read gyroscope values
                gyro_x = read_word(MPU6050_ADDR, GYRO_XOUT_H)
                gyro_y = read_word(MPU6050_ADDR, GYRO_YOUT_H)
                gyro_z = read_word(MPU6050_ADDR, GYRO_ZOUT_H)

                # Update step detection values
                if len(future_values) < WINDOW_SIZE:
                    future_values.append(accel_z)
                    continue
                else:
                    past_values.append(future_values.popleft())
                    future_values.append(accel_z)

                # Detect steps
                average_past = calculate_moving_average(past_values)
                average_future = calculate_moving_average(future_values)
                current_time = time.time()

                if detect_step(average_past, accel_z, average_future, last_step_time, current_time):
                    step_count += 1
                    last_step_time = current_time

                # Create data string
                data_str = f"SENSOR,{HEAD_ID},{SENSOR_ID},{accel_x},{accel_y},{accel_z},{gyro_x},{gyro_y},{gyro_z},{step_count}"
                file.write(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}: {data_str}\n")

                # Sleep to match sensor sampling rate
                time.sleep(0.04)
        except Exception as e:
            print(f"Error in write_accel: {e}")


def record_and_play():
    """Record and pass-through audio while saving it to a file."""
    global is_active

    filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".wav"
    print(f"Recording to {filename} and playing audio...")

    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit audio
        wf.setframerate(sample_rate)

        def audio_callback(indata, outdata, frames, time, status):
            """Audio processing callback."""
            if status:
                print(f"Stream status: {status}")

            amplified_data = (indata * MIC_GAIN).astype('int16')  # Adjust gain
            outdata[:] = (amplified_data * OUTPUT_VOLUME).astype('int16')  # Output audio
            wf.writeframes(amplified_data.tobytes())  # Save to WAV

        with sd.Stream(
            samplerate=sample_rate,
            channels=channels,
            dtype='int16',
            callback=audio_callback,
            blocksize=1024,
            device=(input_device, output_device)
        ):
            while is_active:
                sd.sleep(100)

    print("Recording and playback stopped.")


@app.route("/audio", methods=["POST"])
def control_audio():
    """Handle audio recording and playback via HTTP."""
    global is_active, audio_thread

    action = request.json.get("action")
    if action == "start":
        if is_active:
            return jsonify({"status": "error", "message": "Already active"}), 400

        is_active = True
        audio_thread = threading.Thread(target=record_and_play, daemon=True)
        audio_thread.start()
        accel_thread = threading.Thread(target=write_accel, daemon=True)
        accel_thread.start()
        return jsonify({"status": "success", "message": "Started recording and monitoring"})

    elif action == "stop":
        if not is_active:
            return jsonify({"status": "error", "message": "Not currently active"}), 400

        is_active = False
        audio_thread.join()  # Wait for thread to finish
        return jsonify({"status": "success", "message": "Stopped recording and monitoring"})

    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400


# Run the Flask server in threaded mode
app.run(host="0.0.0.0", port=5000, threaded=True)
