#!/bin/bash
# Script per inviare comandi AT tramite minicom

# Imposta il dispositivo seriale e il baud rate (modifica se necessario)
DEVICE="/dev/ttyUSB2"
BAUD=115200

# File temporaneo per lo script di minicom
SCRIPT_FILE=$(mktemp)

# Crea il file di script per minicom
cat <<EOF > "$SCRIPT_FILE"
send "AT+CUSBPIDSWITCH=9011,1,1\r"
wait "OK"
send "AT+CGDCONT=1,\"IP\",\"m2m.vodafone.it\"\r"
wait "OK"
EOF

# Avvia minicom in modalità script
minicom -b "$BAUD" -D "$DEVICE" -S "$SCRIPT_FILE"

# Rimuove il file temporaneo
rm "$SCRIPT_FILE"
