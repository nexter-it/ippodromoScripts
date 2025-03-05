#!/bin/bash
# Script per configurare il SIM7600 in modalità RNDIS con APN personalizzato
# e richiedere un indirizzo IP sulla porta usb0.

# Configurazioni: modifica DEVICE e BAUD se necessario
DEVICE="/dev/ttyUSB2"
BAUD=115200

# Funzione per inviare comandi AT tramite minicom
send_at_command() {
    local cmd="$1"
    local temp_script
    temp_script=$(mktemp)

    # Crea lo script temporaneo per minicom
    cat <<EOF > "$temp_script"
send "$cmd\r"
wait "OK"
EOF

    # Avvia minicom in modalità script e invia il comando
    minicom -b "$BAUD" -D "$DEVICE" -S "$temp_script"
    rm "$temp_script"
}

echo "Invio del comando AT+CUSBPIDSWITCH per configurare la modalità USB..."
send_at_command 'AT+CUSBPIDSWITCH=9011,1,1'

echo "Attendo 20 secondi per il riavvio del modulo..."
sleep 20

echo "Invio del comando AT+CGDCONT per impostare l'APN..."
send_at_command 'AT+CGDCONT=1,"IP","m2m.vodafone.it"'

echo "Richiedo un indirizzo IP sull'interfaccia usb0..."
sudo dhclient -v usb0

echo "Configurazione completata."
