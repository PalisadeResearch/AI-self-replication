#!/usr/bin/env bash
# chain_watcher.sh — Background daemon that detects qwen-code completion and uploads logs to Langfuse.
#
# Pre-deployed on each VM by setup_experiment_chain.sh.
# Watches for qwen processes, waits for them to finish, then uploads their JSONL output.
#
# Configuration (written by setup script):
#   /opt/chain/env        — Langfuse credentials (sourced)
#   /opt/chain/tags.txt   — comma-separated tags for this VM (e.g. "run1,vm-canada,benchmark_v2")
#   /opt/chain/vm-id.txt  — VM identity (e.g. "vm-canada")
#
# Logs to /opt/chain/watcher.log

set -uo pipefail

CHAIN_DIR="/opt/chain"
LOG="$CHAIN_DIR/watcher.log"
UPLOAD_SCRIPT="$CHAIN_DIR/chain_upload_trace.py"

mkdir -p "$CHAIN_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# Source Langfuse credentials
if [[ -f "$CHAIN_DIR/env" ]]; then
    set -a; source "$CHAIN_DIR/env"; set +a
fi

VM_ID="unknown"
[[ -f "$CHAIN_DIR/vm-id.txt" ]] && VM_ID=$(cat "$CHAIN_DIR/vm-id.txt")

log "Watcher started on $VM_ID (PID $$)"

find_qwen_pid() {
    # Find a qwen process that's running with --yolo (our agent marker)
    pgrep -f 'qwen.*--yolo' 2>/dev/null | head -1
}

find_log_file() {
    # The agent typically writes to /tmp/agent2.log (from the prompt command)
    # or the chain launcher writes to a timestamped file
    # Check common locations, return the most recently modified one
    local candidates=()
    for f in /tmp/agent2.log /tmp/qwen_inference.log /tmp/agent_run_*.jsonl /tmp/chain_run_*.jsonl /tmp/qwen_*.log; do
        [[ -f "$f" ]] && candidates+=("$f")
    done
    # Also check home dirs of chain users
    for home in /home/*/; do
        for f in "$home".logs/run-*.jsonl; do
            [[ -f "$f" ]] && candidates+=("$f")
        done
    done
    # Also check root's home
    for f in /root/.logs/run-*.jsonl; do
        [[ -f "$f" ]] && candidates+=("$f")
    done

    if [[ ${#candidates[@]} -eq 0 ]]; then
        echo ""
        return
    fi

    # Return the most recently modified file that hasn't been uploaded yet
    for f in $(ls -t "${candidates[@]}" 2>/dev/null); do
        if [[ ! -f "${f}.uploaded" ]]; then
            echo "$f"
            return
        fi
    done
    echo ""
}

upload_log() {
    local jsonl_path="$1"
    local tags_file="$CHAIN_DIR/tags.txt"

    if [[ ! -f "$jsonl_path" ]]; then
        log "No log file to upload"
        return 1
    fi

    if [[ -f "${jsonl_path}.uploaded" ]]; then
        log "Already uploaded: $jsonl_path"
        return 0
    fi

    local file_size
    file_size=$(wc -c < "$jsonl_path" 2>/dev/null || echo 0)
    if [[ "$file_size" -lt 10 ]]; then
        log "Log file too small ($file_size bytes), skipping: $jsonl_path"
        return 1
    fi

    log "Uploading $jsonl_path ($file_size bytes)"

    if [[ -f "$tags_file" ]]; then
        python3 "$UPLOAD_SCRIPT" "$jsonl_path" --tags-file "$tags_file" >> "$LOG" 2>&1
    else
        python3 "$UPLOAD_SCRIPT" "$jsonl_path" --tags "$VM_ID,geo-chain" >> "$LOG" 2>&1
    fi

    local rc=$?
    if [[ $rc -eq 0 ]]; then
        log "Upload successful: $jsonl_path"
    else
        log "Upload FAILED (rc=$rc): $jsonl_path"
    fi
    return $rc
}

# Main loop: watch for qwen processes, upload when they finish
while true; do
    # Wait for a qwen process to appear
    QWEN_PID=""
    while [[ -z "$QWEN_PID" ]]; do
        QWEN_PID=$(find_qwen_pid)
        if [[ -z "$QWEN_PID" ]]; then
            sleep 10
        fi
    done

    log "Detected qwen process PID=$QWEN_PID"

    # Wait for the process to finish
    while kill -0 "$QWEN_PID" 2>/dev/null; do
        sleep 15
    done

    log "qwen process PID=$QWEN_PID finished"

    # Brief pause to let file writes flush
    sleep 5

    # Find and upload the log
    LOG_FILE=$(find_log_file)
    if [[ -n "$LOG_FILE" ]]; then
        upload_log "$LOG_FILE"
    else
        log "No log file found after qwen exit"
    fi

    # Continue watching for the next qwen process (shouldn't happen in linear chain, but just in case)
    sleep 10
done
