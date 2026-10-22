#!/usr/bin/env bash
# Certificado autofirmado para servir Mi Voluntad por HTTPS en la red local
# (el micrófono del móvil solo funciona en páginas https).
# Vuelva a ejecutarlo si cambia la IP del portátil (por ejemplo, en otra wifi).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p certs

SAN="DNS:localhost,IP:127.0.0.1"
for ip in $(hostname -I); do
  SAN="$SAN,IP:$ip"
done

openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=Mi Voluntad (local)" \
  -addext "subjectAltName=$SAN" 2>/dev/null
chmod 600 certs/key.pem

echo "Certificado creado en certs/ (válido 365 días) para: $SAN"
echo "Arranque con:  python server.py --host 0.0.0.0 --https"
