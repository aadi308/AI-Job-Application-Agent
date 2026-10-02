#!/bin/sh
set -eu

python /app/scripts/init_db.py
exec streamlit run /app/app/dashboard.py \
  --server.address 0.0.0.0 \
  --server.port "${PORT:-8501}" \
  --server.headless true
