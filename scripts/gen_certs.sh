#!/usr/bin/env bash
# Generate a self-signed CA + broker certificate for Mosquitto TLS.  OWNER: Part 1
set -euo pipefail
cd "$(dirname "$0")/../mosquitto/certs"
CN="${1:-localhost}"

openssl req -new -x509 -days 365 -nodes -subj "/CN=SmartHome-CA" \
  -keyout ca.key -out ca.crt
openssl req -new -nodes -subj "/CN=${CN}" -keyout server.key -out server.csr
printf "subjectAltName=DNS:%s,DNS:mosquitto,IP:127.0.0.1\n" "$CN" > san.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 365 -extfile san.ext
rm -f server.csr san.ext
chmod 644 server.key   # mosquitto container must be able to read it
echo "Certs written to mosquitto/certs/"
