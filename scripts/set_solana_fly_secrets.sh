#!/usr/bin/env bash
set -euo pipefail

APP="${FLY_APP:-crypto-agent-serene-surf-3922}"

printf 'Fly app: %s\n' "$APP"
printf 'Paste Solana wallet PUBLIC address: '
IFS= read -r SOLANA_WALLET_ADDRESS

printf 'Paste Solana wallet PRIVATE key (hidden): '
stty -echo
IFS= read -r SOLANA_WALLET_PRIVATE_KEY
stty echo
printf '\n'

if [[ -z "${SOLANA_WALLET_ADDRESS}" ]]; then
  echo "ERROR: SOLANA_WALLET_ADDRESS is empty" >&2
  exit 1
fi

if [[ -z "${SOLANA_WALLET_PRIVATE_KEY}" ]]; then
  echo "ERROR: SOLANA_WALLET_PRIVATE_KEY is empty" >&2
  exit 1
fi

flyctl secrets set \
  SOLANA_WALLET_ADDRESS="${SOLANA_WALLET_ADDRESS}" \
  SOLANA_WALLET_PRIVATE_KEY="${SOLANA_WALLET_PRIVATE_KEY}" \
  CHAINS_TO_SCAN="base,solana" \
  -a "${APP}"

printf '\nSecrets submitted to Fly.io. Verifying presence without printing values...\n'
flyctl ssh console -a "${APP}" -C 'python -c "from config import get_settings; s=get_settings(); print({\"chains\": s.enabled_chains, \"solana_wallet_address_set\": bool(s.solana_wallet_address), \"solana_private_key_set\": bool(s.solana_wallet_private_key), \"mode\": s.agent_mode})"'
