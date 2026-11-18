#!/usr/bin/env bash
# Build individual MQTT credentials for Part 1 without printing passwords.
# Uses Mosquitto's password-file conversion mode (-U) so secrets aren't passed
# as Docker command-line arguments.
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
    echo "ERROR: Missing .env file" >&2
    exit 1
fi

# Load only from the team's local, Git-ignored environment file.
set -a
# shellcheck disable=SC1091
source .env
set +a

appliances=(refrigerator microwave washing_machine water_heater air_conditioner television)
for appliance in "${appliances[@]}"; do
    upper="$(printf '%s' "$appliance" | tr '[:lower:]' '[:upper:]')"
    key="PLUG_${upper}_PASSWORD"
    if [[ -z "${!key:-}" ]]; then
        echo "ERROR: Missing $key in .env" >&2
        exit 1
    fi
done
: "${PROCESSOR_PASSWORD:?Missing PROCESSOR_PASSWORD in .env}"
PROCESSOR_USER="${PROCESSOR_USER:-processor}"

# Build a file in a restricted temporary directory, atomically replacing the
# active password file only after every password is hashed successfully.
umask 077
tmpdir="$(mktemp -d mosquitto/config/.passwd-build.XXXXXX)"
trap 'rm -rf "$tmpdir"' EXIT
plainfile="$tmpdir/passwd"
: > "$plainfile"
chmod 600 "$plainfile"

for appliance in "${appliances[@]}"; do
    upper="$(printf '%s' "$appliance" | tr '[:lower:]' '[:upper:]')"
    key="PLUG_${upper}_PASSWORD"
    printf '%s:%s\n' "$appliance" "${!key}" >> "$plainfile"
done
printf '%s:%s\n' "$PROCESSOR_USER" "$PROCESSOR_PASSWORD" >> "$plainfile"

# -U converts user:plaintext-password lines to Mosquitto password hashes.
# No passwords are printed or included in Docker command-line arguments.
docker run --rm \
    -v "$PWD/mosquitto/config:/m" \
    --entrypoint mosquitto_passwd \
    eclipse-mosquitto:2.0.20 \
    -U "/m/$(basename "$tmpdir")/passwd"

chmod 600 "$plainfile"
mv -f "$plainfile" mosquitto/config/passwd
chmod 600 mosquitto/config/passwd
printf 'Updated mosquitto/config/passwd with 7 accounts. No passwords displayed.\n'
printf 'Restart Mosquitto after checking the account names.\n'
