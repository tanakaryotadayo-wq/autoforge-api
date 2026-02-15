#!/bin/bash
# AutoForge DB — Daily Backup to Google Drive
# Usage: ./scripts/backup_db.sh
# Cron/launchd: 毎日AM3:00に自動実行

set -euo pipefail

# --- Config ---
DB_NAME="autoforge"
DB_USER="autoforge"
DB_HOST="localhost"
DB_PORT="5432"
BACKUP_DIR="$HOME/Library/CloudStorage/GoogleDrive-tanakaryotadayo@gmail.com/マイドライブ/autoforge-backups"
RETAIN_DAYS=30

# --- Setup ---
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/autoforge_${TIMESTAMP}.sql.gz"

# --- Dump ---
echo "[$(date)] Starting backup..."
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  --no-owner --no-privileges --clean --if-exists \
  | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date)] Backup complete: $BACKUP_FILE ($SIZE)"

# --- Cleanup old backups ---
find "$BACKUP_DIR" -name "autoforge_*.sql.gz" -mtime +$RETAIN_DAYS -delete
REMAINING=$(ls -1 "$BACKUP_DIR"/autoforge_*.sql.gz 2>/dev/null | wc -l | tr -d ' ')
echo "[$(date)] Retained $REMAINING backups (last ${RETAIN_DAYS} days)"
