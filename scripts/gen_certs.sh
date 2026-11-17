#!/usr/bin/env bash
# Generate local TLS certificates, or renew only the broker certificate.
# OWNER: Part 1 — Smart Home Energy Monitoring
set -euo pipefail
cd "$(dirname "$0")/.."

CERT_DIR="mosquitto/certs"
PRIVATE_DIR="mosquitto/private"
BROKER_KEY="mosquitto/config/server.key"
mkdir -p "$CERT_DIR" "$PRIVATE_DIR" "$(dirname "$BROKER_KEY")"
umask 077

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cat > "$TMP_DIR/server.ext" <<'EXT'
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
subjectAltName = DNS:localhost,DNS:mosquitto,IP:127.0.0.1
EXT

case "${1:-create}" in
  create)
    for file in "$CERT_DIR/ca.crt" "$CERT_DIR/server.crt" \
                "$PRIVATE_DIR/ca.key" "$BROKER_KEY"; do
      if [ -e "$file" ]; then
        echo "Existing certificate material found: $file" >&2
        echo "Use --renew-server to replace the certificate without replacing keys." >&2
        exit 1
      fi
    done

    cat > "$TMP_DIR/ca.cnf" <<'CONFIG'
[req]
prompt = no
distinguished_name = identity
x509_extensions = ca_extensions
[identity]
CN = SmartHome-Local-CA
[ca_extensions]
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
CONFIG

    openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 365 \
      -config "$TMP_DIR/ca.cnf" \
      -keyout "$PRIVATE_DIR/ca.key" -out "$CERT_DIR/ca.crt"

    openssl req -new -newkey rsa:3072 -nodes -sha256 \
      -subj "/CN=localhost" \
      -keyout "$BROKER_KEY" -out "$TMP_DIR/server.csr"
    ;;

  --renew-server)
    for file in "$CERT_DIR/ca.crt" "$PRIVATE_DIR/ca.key" "$BROKER_KEY"; do
      if [ ! -f "$file" ]; then
        echo "Required existing CA or server key not found: $file" >&2
        exit 1
      fi
    done

    # Use the existing broker private key and the existing local CA.
    openssl req -new -sha256 -key "$BROKER_KEY" \
      -subj "/CN=localhost" -out "$TMP_DIR/server.csr"
    ;;

  *)
    echo "Usage: bash scripts/gen_certs.sh [--renew-server]" >&2
    exit 2
    ;;
esac

# Include explicit AKI and SKI extensions so Python 3.13 strict verification works.
openssl x509 -req -sha256 -days 365 \
  -in "$TMP_DIR/server.csr" \
  -CA "$CERT_DIR/ca.crt" -CAkey "$PRIVATE_DIR/ca.key" \
  -CAserial "$PRIVATE_DIR/ca.srl" -CAcreateserial \
  -extfile "$TMP_DIR/server.ext" \
  -out "$TMP_DIR/server.crt"

# Verify before replacing the installed certificate.
openssl verify -CAfile "$CERT_DIR/ca.crt" "$TMP_DIR/server.crt"
cp "$TMP_DIR/server.crt" "$CERT_DIR/server.crt"
chmod 600 "$PRIVATE_DIR/ca.key" "$BROKER_KEY"
chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/server.crt"

echo "TLS server certificate generated successfully."
echo "Existing CA and server private key retained when using --renew-server."
echo "Broker certificate: $CERT_DIR/server.crt"
