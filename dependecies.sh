#!/bin/bash

# Aggiorna la lista dei pacchetti
echo "Updating package list..."
sudo apt update

# Installa le dipendenze principali
echo "Installing required packages..."
sudo apt install -y git gpsd gpsd-clients python3-gps python3-pip wireguard resolvconf dnsmasq hostapd i2c-tools

# Installa i pacchetti Python necessari
echo "Installing Python packages..."
pip3 install gpsd-py3 --break-system-packages
pip3 install psutil --break-system-packages
pip3 install smbus --break-system-packages

# Verifica l'installazione di gpsd con cgps
echo "Testing GPSD setup..."
cgps -s

# Installa tmux per eventuali sessioni persistenti
echo "Installing tmux..."
sudo apt install -y tmux

# Configura il servizio systemd per horsemonitor
echo "Setting up horsemonitor service..."
sudo cp horsemonitor.service /etc/systemd/system/horsemonitor.service
sudo systemctl daemon-reload
sudo systemctl enable horsemonitor.service
sudo systemctl start horsemonitor.service

# Mostra lo stato del servizio per confermare che sia attivo
echo "Checking horsemonitor service status..."
sudo systemctl status horsemonitor.service

echo "All dependencies and service have been set up successfully!"
