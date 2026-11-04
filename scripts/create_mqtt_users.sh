#!/usr/bin/env bash
# Create the Mosquitto password file using the passwords in .env.  OWNER: Part 1
set -euo pipefail
cd "$(dirname "$0")/.."
source .env
PW=mosquitto/config/passwd
: > "$PW"
run() { docker run --rm -v "$PWD/mosquitto/config:/m" eclipse-mosquitto:2.0.20 mosquitto_passwd -b /m/passwd "$1" "$2"; }
for a in refrigerator microwave washing_machine water_heater air_conditioner television; do
  run "$a" "$PLUG_PASSWORD"          # TODO Part 1: separate password per plug
done
run "$PROCESSOR_USER" "$PROCESSOR_PASSWORD"
echo "Users written to $PW"
