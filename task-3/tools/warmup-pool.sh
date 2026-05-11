#!/usr/bin/env bash
# warmup-pool.sh
#
# Fire the pool-refill webhook for every material × lang combo that has
# < 3 pool entries. Idempotent — safe to run repeatedly.
#
# Use this after:
#   - First-time deployment (existing materials have empty pools)
#   - Restoring from a backup
#   - Manual debugging when pool gets out of sync
#
# n8n's webhook responds 200 immediately and processes in background, so
# this script returns fast; actual generation happens async (each quiz
# takes ~30-60s via Sonnet 4.5). Check progress with:
#   docker exec task3-postgres psql -U n8n -d n8n -c \
#     "SELECT material_id, lang, count(*) FROM app.quiz_pool GROUP BY 1,2;"
#
# Usage:
#   bash tools/warmup-pool.sh [--lang en|ru|both]
#
# Default: --lang both.

set -euo pipefail

NGROK_DOMAIN="${NGROK_DOMAIN:-seniorprepcoach.ngrok.dev}"
WEBHOOK_URL="https://${NGROK_DOMAIN}/webhook/pool-refill"
LANGS="${1:-both}"

case "$LANGS" in
  en)   LANG_LIST="en" ;;
  ru)   LANG_LIST="ru" ;;
  both|--lang=both|"") LANG_LIST="en ru" ;;
  *)    echo "Usage: $0 [en|ru|both]"; exit 1 ;;
esac

echo "Warming up pool via $WEBHOOK_URL"
echo "Languages: $LANG_LIST"
echo

# Fetch all material IDs from Postgres
MATERIAL_IDS=$(docker exec task3-postgres psql -U n8n -d n8n -t -A -c \
  "SELECT id FROM app.learning_materials ORDER BY id;")

if [ -z "$MATERIAL_IDS" ]; then
  echo "No materials found. Nothing to warm up."
  exit 0
fi

COUNT=0
for material_id in $MATERIAL_IDS; do
  for lang in $LANG_LIST; do
    # Check current pool depth
    DEPTH=$(docker exec task3-postgres psql -U n8n -d n8n -t -A -c \
      "SELECT COUNT(*) FROM app.quiz_pool WHERE material_id = $material_id AND lang = '$lang';")
    if [ "$DEPTH" -ge 3 ]; then
      echo "  material=$material_id lang=$lang already has $DEPTH entries, skip"
      continue
    fi
    echo "  Firing refill: material=$material_id lang=$lang (current depth: $DEPTH)"
    curl -sk -X POST "$WEBHOOK_URL" \
      -H "Content-Type: application/json" \
      -d "{\"material_id\":$material_id,\"lang\":\"$lang\"}" > /dev/null
    COUNT=$((COUNT + 1))
    # Tiny stagger to avoid spiking Anthropic rate limit
    sleep 1
  done
done

echo
echo "Fired $COUNT refill triggers. Pool fills in background — each entry"
echo "takes ~30-60s. Monitor progress via:"
echo "  docker exec task3-postgres psql -U n8n -d n8n -c \\"
echo "    \"SELECT material_id, lang, COUNT(*) FROM app.quiz_pool GROUP BY 1,2 ORDER BY 1,2;\""
