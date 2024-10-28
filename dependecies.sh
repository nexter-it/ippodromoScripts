#!/bin/bash

# Aggiorna la lista dei pacchetti
echo "Updating package list..."
sudo apt update

# Installa le dipendenze principali
echo "Installing required packages..."
sudo apt install -y git gpsd gpsd-clients python3-gps python3-pip wireguard resolvconf dnsmasq hostapd

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

echo "All dependencies have been installed successfully!"
