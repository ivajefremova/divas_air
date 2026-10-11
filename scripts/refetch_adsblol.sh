#!/usr/bin/env bash
# Re-download the adsb.lol days behind data/processed/adsblol_*.parquet and re-filter them
# with filter_adsblol_v2.py (adds alt_geom_m and pos_source) into data/processed/adsblol_v2/.
#
# usage: scripts/refetch_adsblol.sh        (run from the repo root)
#
# Days: every adsblol_fco_<date>.parquet listed in docs/DATA_INVENTORY.md.
# On the Baltic day the jam and control files are written as well. Their boxes are not recorded
# in the inventory or the scripts; these are the lat/lon extents of the existing files, which sit
# on round numbers (jam 53.000002..56.499986 x 17.500044..25.499804, control 44.500029..48.0 x 0.0..7.99999).
#
# Never overwrites a processed file: a day is skipped when all its v2 outputs exist.
# Stops if free disk is under MIN_FREE_GB. Aborts after the first processed day if any file's row
# count differs from the existing one by more than 1 % or alt_geom_m is under 50 % non-null.
# Any other failure is logged and the next day runs.
set -uo pipefail

REPO="adsblol/globe_history_2026"
RETRIES=3
MIN_FREE_GB=15
MAX_ROW_DIFF_PCT=1
MIN_ALT_GEOM_NN_PCT=50
BALTIC_DAY="2026-10-05"
JAM_BOX="53.0 17.5 56.5 25.5"        # lat_min lon_min lat_max lon_max
CONTROL_BOX="44.5 0.0 48.0 8.0"

# Overridable for testing.
PY="${PY:-.venv/bin/python}"
GH="${GH:-gh}"
INVENTORY="${INVENTORY:-docs/DATA_INVENTORY.md}"
RAW_ROOT="${RAW_ROOT:-data/raw/adsblol}"
OLD_DIR="${OLD_DIR:-data/processed}"
OUT_DIR="${OUT_DIR:-data/processed/adsblol_v2}"
SCRIPTS="${SCRIPTS:-scripts}"
RETRY_SLEEP_S="${RETRY_SLEEP_S:-30}"

mkdir -p "$RAW_ROOT" "$OUT_DIR"
LOG="$OUT_DIR/refetch_$(date -u +%Y%m%dT%H%M%SZ).log"
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

mapfile -t DAYS < <(grep -o 'adsblol_fco_[0-9-]*\.parquet' "$INVENTORY" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' | sort -u)
if [ ${#DAYS[@]} -eq 0 ]; then log "no FCO days found in $INVENTORY"; exit 1; fi
log "days: ${DAYS[*]}"

SUMMARY=()      # "date|file|status|rows_v2|rows_old|diff_pct|alt_geom_nn_pct"
GATE_DONE=0

free_gb() { df -P -BG "$RAW_ROOT" | awk 'NR==2 {sub("G", "", $4); print $4}'; }

# Outputs for one day: "name|box" (empty box = filter default, the FCO approach box).
outputs_for() {
    echo "adsblol_fco_$1.parquet|"
    if [ "$1" = "$BALTIC_DAY" ]; then
        echo "adsblol_jam_$1.parquet|$JAM_BOX"
        echo "adsblol_control_$1.parquet|$CONTROL_BOX"
    fi
}

# Prints the comparison and, on its last line, "STAT rows_v2 rows_old diff_pct alt_nn_pct".
compare() {
    "$PY" -I - "$1" "$2" <<'EOF'
import sys
from pathlib import Path
import pandas as pd
new, old = Path(sys.argv[1]), Path(sys.argv[2])
d = pd.read_parquet(new).reindex(columns=["alt_geom_m", "pos_source"])  # 0-row files have no columns
n = len(d)
n_old = len(pd.read_parquet(old, columns=["icao24"])) if old.exists() else -1
diff = 100.0 * (n - n_old) / n_old if n_old > 0 else float("nan")
alt_nn = 100.0 * d["alt_geom_m"].notna().mean() if n else 0.0
print(f"  {new.name}: rows v2 {n:,} vs existing {n_old:,} ({diff:+.2f} %)")
print(f"  alt_geom_m non-null {alt_nn:.1f} %")
print("  pos_source share by value:")
for v, s in d["pos_source"].value_counts(dropna=False, normalize=True).items():
    print(f"    {str(v):<16} {100 * s:6.2f} %")
print(f"STAT {n} {n_old} {diff:.4f} {alt_nn:.4f}")
EOF
}

download() {   # $1 date, $2 dest dir
    local tag="v${1//-/.}-planes-readsb-prod-0" attempt
    for attempt in $(seq 0 "$RETRIES"); do
        [ "$attempt" -gt 0 ] && { log "  retry $attempt/$RETRIES for $tag"; sleep $((attempt * RETRY_SLEEP_S)); }
        "$GH" release download "$tag" -R "$REPO" -D "$2" --clobber && return 0
    done
    return 1
}

process_day() {   # $1 date; returns 0 ok, 1 failure, 2 gate abort, 3 disk stop
    local day="$1" raw="$RAW_ROOT/$1" todo=() line name box out tmp status stats rows old diff alt bad=0

    while IFS= read -r line; do
        name="${line%%|*}"
        if [ -e "$OUT_DIR/$name" ]; then
            log "  $name exists in $OUT_DIR, not touched"
            SUMMARY+=("$day|$name|skipped (exists)||||")
        else
            todo+=("$line")
        fi
    done < <(outputs_for "$day")
    [ ${#todo[@]} -eq 0 ] && { log "$day: all v2 outputs exist, skipping"; return 0; }

    local gb; gb=$(free_gb)
    if [ "$gb" -lt "$MIN_FREE_GB" ]; then log "free disk ${gb} GB < ${MIN_FREE_GB} GB, stopping"; return 3; fi
    log "$day: ${gb} GB free, downloading"

    if [ -e "$raw" ]; then log "  $raw already exists, refusing to reuse it"; SUMMARY+=("$day|-|FAILED (raw dir exists)||||"); return 1; fi
    mkdir -p "$raw"
    if ! download "$day" "$raw"; then
        log "  download failed after $RETRIES retries"; rm -rf "$raw"
        SUMMARY+=("$day|-|FAILED (download)||||"); return 1
    fi
    if ! "$PY" -I "$SCRIPTS/unpack_release.py" "$raw" 2>&1 | tee -a "$LOG"; then
        log "  unpack failed"; rm -rf "$raw"
        SUMMARY+=("$day|-|FAILED (unpack)||||"); return 1
    fi

    for line in "${todo[@]}"; do
        name="${line%%|*}"; box="${line#*|}"; out="$OUT_DIR/$name"; tmp="$OUT_DIR/.$name.tmp"
        # shellcheck disable=SC2086  # box is intentionally split into four arguments
        if ! "$PY" -I "$SCRIPTS/filter_adsblol_v2.py" "$raw" "$tmp" $box 2>&1 | tee -a "$LOG"; then
            log "  filter failed for $name"; rm -f "$tmp"; SUMMARY+=("$day|$name|FAILED (filter)||||"); continue
        fi
        if [ -e "$out" ] || ! mv -n "$tmp" "$out" || [ -e "$tmp" ]; then
            log "  $out appeared meanwhile, left untouched"; rm -f "$tmp"; SUMMARY+=("$day|$name|FAILED (exists)||||"); continue
        fi
        if ! stats=$(compare "$out" "$OLD_DIR/$name" 2>&1); then
            log "  compare failed for $name: $stats"; SUMMARY+=("$day|$name|FAILED (compare)||||"); continue
        fi
        grep -v '^STAT ' <<<"$stats" | tee -a "$LOG"
        read -r _ rows old diff alt < <(grep '^STAT ' <<<"$stats")
        status=ok
        if [ "$GATE_DONE" -eq 0 ] && awk -v d="$diff" -v a="$alt" -v md="$MAX_ROW_DIFF_PCT" -v ma="$MIN_ALT_GEOM_NN_PCT" \
            'BEGIN { if (d == "nan" || (d < 0 ? -d : d) > md || a < ma) exit 0; exit 1 }'; then
            log "  GATE FAILED for $name: row diff ${diff} % (max ${MAX_ROW_DIFF_PCT}), alt_geom_m non-null ${alt} % (min ${MIN_ALT_GEOM_NN_PCT})"
            bad=1; status="GATE FAILED"
        fi
        SUMMARY+=("$day|$name|$status|$rows|$old|$diff|$alt")
    done

    rm -rf "$raw"
    log "  deleted $raw"
    if [ "$GATE_DONE" -eq 0 ]; then
        [ "$bad" -eq 1 ] && return 2
        # The gate is passed once a day produced at least one compared file.
        printf '%s\n' "${SUMMARY[@]}" | grep -q "^$day|.*|ok|" && GATE_DONE=1 && log "  first-day gate passed"
    fi
    return 0
}

print_summary() {
    log "summary (log: $LOG)"
    {
        echo "date|file|status|rows_v2|rows_old|diff_%|alt_geom_nn_%"
        printf '%s\n' "${SUMMARY[@]}"
    } | column -t -s '|' | tee -a "$LOG"
}

for day in "${DAYS[@]}"; do
    process_day "$day"
    rc=$?
    if [ $rc -eq 2 ]; then log "ABORT: first-day check failed, nothing else will run"; print_summary; exit 2; fi
    if [ $rc -eq 3 ]; then print_summary; exit 3; fi
done
print_summary
