#!/bin/sh
set -eu

if [ "${APP_MODE:-local}" != "production" ]; then
  python /app/scripts/init_db.py
fi
exec streamlit run /app/app/dashboard.py \
  --server.address 0.0.0.0 \
  --server.port "${PORT:-8501}" \
  --server.headless true
