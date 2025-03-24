#!/bin/bash

# Aggiorna la lista dei pacchetti
echo "Updating package list..."
sudo apt update

# Installa le dipendenze principali
echo "Installing required packages..."
sudo apt install -y git gpsd gpsd-clients python3-gps python3-pip wireguard resolvconf dnsmasq hostapd i2c-tools libportaudio2

# Setta volume microfono e output
amixer set Capture 90%
amixer set Master 90%

# Installa i pacchetti Python necessari
echo "Installing Python packages..."
pip3 install gpsd-py3 --break-system-packages
pip3 install psutil --break-system-packages
pip3 install smbus --break-system-packages
pip3 install sounddevice --break-system-packages
pip3 install filterpy --break-system-packages

sudo pip3 install mpu6050-raspberrypi --break-system-packages
sudo pip3 install pyserial --break-system-packages
sudo pip3 install pynmea2 --break-system-packages

# Installa tmux per eventuali sessioni persistenti
echo "Installing tmux..."
sudo apt install -y tmux

# Configura il servizio systemd per horsemonitor
echo "Setting up horsemonitor service..."
sudo cp horsemonitor.service /etc/systemd/system/horsemonitor.service
sudo systemctl daemon-reload
sudo systemctl enable horsemonitor.service
sudo systemctl start horsemonitor.service

# Mostra lo stato del servizio horsemonitor
echo "Checking horsemonitor service status..."
sudo systemctl status horsemonitor.service

# Configura il servizio systemd per receiver_gestionale
echo "Setting up receiver_gestionale service..."
sudo cp receiver_gestionale.service /etc/systemd/system/receiver_gestionale.service
sudo systemctl daemon-reload
sudo systemctl enable receiver_gestionale.service
sudo systemctl start receiver_gestionale.service

# Mostra lo stato del servizio receiver_gestionale
echo "Checking receiver_gestionale service status..."
sudo systemctl status receiver_gestionale.service

echo "Enabling ssh..."
sudo systemctl enable ssh
sudo systemctl start ssh

# Abilito VPN solo se vpn.conf esiste nella directory corrente
if [ -f "vpn.conf" ]; then
    echo "Enabling VPN..."
    sudo cp vpn.conf /etc/wireguard/
    sudo wg-quick up vpn
    sudo systemctl enable wg-quick@vpn
    sudo systemctl start wg-quick@vpn
    sudo systemctl status wg-quick@vpn
else
    echo "vpn.conf non trovato. Salto la configurazione della VPN."
fi

# Avvio servizio per acquisizione accellerometri e giroscopi
echo "Setting up accgir service..."
CONFIG_FILE="/boot/firmware/config.txt"

# Aggiunge la riga per abilitare I2C se non già presente
if ! grep -q "^dtparam=i2c_arm=on" "$CONFIG_FILE"; then
  echo "Abilitazione I2C in $CONFIG_FILE"
  echo "dtparam=i2c_arm=on" | sudo tee -a "$CONFIG_FILE"
else
  echo "I2C è già abilitato in $CONFIG_FILE"
fi

# Carica il modulo i2c-dev se non è già caricato
if ! lsmod | grep -q "^i2c_dev"; then
  echo "Caricamento del modulo i2c-dev..."
  sudo modprobe i2c-dev
fi

sudo timedatectl set-timezone Europe/Rome
sudo mkdir logAccGir
sudo cp accgir.service /etc/systemd/system/accgir.service
sudo systemctl daemon-reload
sudo systemctl enable accgir.service
sudo systemctl start accgir.service
sudo systemctl status accgir.service

echo "All dependencies and services have been set up successfully!"
echo "Rebooting in 10 seconds..."

sleep 10
sudo reboot
