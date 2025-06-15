#!/bin/bash

DATASET_JSON="../NYU_CTF_Bench/test_dataset.json"
MODEL_NAME="vllm:Qwen2.5-32B-Instruct" # "bedrock:us.anthropic.claude-3-5-sonnet-20241022-v2:0"
IMAGE_NAME="sweagent/enigma:latest"
CONFIG_FILE="config/default_ctf.yaml"
HOST_URL="http://localhost:8000"
PER_INSTANCE_STEP_LIMIT=40

# export SWE_AGENT_ACTION_TIMEOUT=60
# Check if indexes were provided
START_INDEX=$1
END_INDEX=$2
TRY_TIMES=$3
PARALLEL_TASKS=50

# Set default values
if [ -z "$TRY_TIMES" ]; then
    TRY_TIMES=1
else
    # Validate that TRY_TIMES is a positive number
    if ! [[ "$TRY_TIMES" =~ ^[0-9]+$ ]] || [ "$TRY_TIMES" -lt 1 ]; then
        echo "Error: Try times must be a positive number"
        echo "Usage: $0 [start_index] [end_index] [try_times] [parallel_tasks]"
        exit 1
    fi
fi

if [ -z "$PARALLEL_TASKS" ]; then
    PARALLEL_TASKS=1
else
    # Validate that PARALLEL_TASKS is a positive number
    if ! [[ "$PARALLEL_TASKS" =~ ^[0-9]+$ ]] || [ "$PARALLEL_TASKS" -lt 1 ]; then
        echo "Error: Parallel tasks must be a positive number"
        echo "Usage: $0 [start_index] [end_index] [try_times] [parallel_tasks]"
        exit 1
    fi
fi

echo "Configuration:"
echo "  Try times per challenge: $TRY_TIMES"
echo "  Parallel tasks: $PARALLEL_TASKS"
echo "  Model: $MODEL_NAME"
echo "  Image: $IMAGE_NAME"

# Session name prefix for tmux sessions
SESSION_PREFIX="qwen25_7b_instruct"

# Function to check if session exists and is active
session_exists() {
    local session_name=$1
    tmux has-session -t "$session_name" 2>/dev/null
}

# Function to get active session count
get_active_session_count() {
    tmux list-sessions 2>/dev/null | grep "^${SESSION_PREFIX}_" | wc -l
}

# Function to run a single challenge in a tmux session
run_challenge() {
    local challenge_id=$1
    local challenge_path=$2
    local try_num=$3
    local instance_id=$4
    
    local DATA_PATH="../NYU_CTF_Bench/${challenge_path}/challenge.json"
    local REPO_PATH="../NYU_CTF_Bench/${challenge_path}/"
    
    # Create unique session name
    local session_name="${SESSION_PREFIX}_${instance_id}_${challenge_id}_try${try_num}"
    
    # Create unique log files for each parallel instance
    local LOG_PREFIX="logs/parallel_${instance_id}_${challenge_id}_try${try_num}"
    local STATUS_FILE="logs/status_${instance_id}_${challenge_id}_try${try_num}.txt"
    mkdir -p logs
    
    if [ "$TRY_TIMES" -gt 1 ]; then
        echo "[Instance $instance_id] Starting tmux session: $session_name for challenge: $challenge_id (attempt $try_num/$TRY_TIMES)"
    else
        echo "[Instance $instance_id] Starting tmux session: $session_name for challenge: $challenge_id"
    fi
    
    # Check if the data and repo paths exist
    if [ ! -f "$DATA_PATH" ]; then
        echo "[Instance $instance_id] Error: Data file not found at $DATA_PATH"
        return 1
    fi
    if [ ! -d "$REPO_PATH" ]; then
        echo "[Instance $instance_id] Error: Repo directory not found at $REPO_PATH"
        return 1
    fi
    
    # Initialize status file
    echo "RUNNING" > "$STATUS_FILE"
    
    # Create the tmux session with improved command structure
    tmux new-session -d -s "$session_name" -c "$(pwd)" bash -c "
        echo 'Starting challenge: $challenge_id (try $try_num)' | tee -a '${LOG_PREFIX}.log'
        echo 'RUNNING' > '$STATUS_FILE'
        
        # Run the main command and capture exit code
        python run.py \\
            --model_name '$MODEL_NAME' \\
            --ctf \\
            --image_name '$IMAGE_NAME' \\
            --data_path '$DATA_PATH' \\
            --repo_path '$REPO_PATH' \\
            --config_file '$CONFIG_FILE' \\
            --host_url '$HOST_URL' \\
            --per_instance_step_limit $PER_INSTANCE_STEP_LIMIT \\
            --temperature=0.7 \\
            --top_p=0.8 \\
            --top_k=20 \\
            --enable_dynamic_ports \\
            2>&1 | tee -a '${LOG_PREFIX}.log'
        
        exit_code=\$?
        
        # Update status based on exit code
        if [ \$exit_code -eq 0 ]; then
            echo 'COMPLETED_SUCCESS' > '$STATUS_FILE'
            echo 'Challenge completed successfully: $challenge_id (try $try_num)' | tee -a '${LOG_PREFIX}.log'
        else
            echo 'COMPLETED_FAILED' > '$STATUS_FILE'
            echo 'Challenge failed: $challenge_id (try $try_num) - Exit code: '\$exit_code | tee -a '${LOG_PREFIX}.log'
        fi
        
        echo 'Session will close in 3 seconds...' | tee -a '${LOG_PREFIX}.log'
        sleep 3
        
        # Mark as finished and exit
        echo 'FINISHED' > '$STATUS_FILE'
        exit \$exit_code
    "
    
    # Store session info for tracking
    echo "${session_name}:${STATUS_FILE}" >> logs/active_sessions.txt
    
    return 0
}

# Function to wait for a slot to become available
wait_for_slot() {
    while true; do
        local active_count=$(get_active_session_count)
        if [ $active_count -lt $PARALLEL_TASKS ]; then
            break
        fi
        
        # Clean up finished sessions
        cleanup_finished_sessions
        sleep 1
    done
}

# Function to clean up finished sessions
cleanup_finished_sessions() {
    if [ ! -f logs/active_sessions.txt ]; then
        return
    fi
    
    # Create temporary file for active sessions
    local temp_file=$(mktemp)
    
    while IFS=':' read -r session_name status_file; do
        if [ -z "$session_name" ] || [ -z "$status_file" ]; then
            continue
        fi
        
        # Check if session still exists
        if ! session_exists "$session_name"; then
            echo "🗑️  Session $session_name no longer exists, removing from tracking"
            continue
        fi
        
        # Check status file
        if [ -f "$status_file" ]; then
            local status=$(cat "$status_file" 2>/dev/null)
            case "$status" in
                "FINISHED"|"COMPLETED_SUCCESS"|"COMPLETED_FAILED")
                    echo "🏁 Session $session_name finished with status: $status"
                    tmux kill-session -t "$session_name" 2>/dev/null
                    ;;
                "RUNNING")
                    # Keep this session active
                    echo "${session_name}:${status_file}" >> "$temp_file"
                    ;;
                *)
                    # Unknown status, check if session is actually running
                    if session_exists "$session_name"; then
                        echo "${session_name}:${status_file}" >> "$temp_file"
                    fi
                    ;;
            esac
        else
            # No status file, check if session exists
            if session_exists "$session_name"; then
                echo "${session_name}:${status_file}" >> "$temp_file"
            fi
        fi
    done < logs/active_sessions.txt
    
    # Replace active sessions file
    mv "$temp_file" logs/active_sessions.txt
}

# Function to clean up all tmux sessions on exit
cleanup() {
    echo "🛑 Cleaning up tmux sessions..."
    
    # Kill all sessions with our prefix
    tmux list-sessions 2>/dev/null | grep "^${SESSION_PREFIX}_" | cut -d: -f1 | while read -r session_name; do
        echo "Killing session: $session_name"
        tmux kill-session -t "$session_name" 2>/dev/null
    done
    
    # Clean up tracking files
    rm -f logs/active_sessions.txt
    rm -f logs/status_*.txt
    
    echo "✅ Cleanup completed"
}

# Set up signal handlers for cleanup
trap cleanup EXIT INT TERM

# Function to show active sessions
show_active_sessions() {
    echo ""
    echo "🖥️  Active tmux sessions:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    local active_sessions=$(tmux list-sessions 2>/dev/null | grep "^${SESSION_PREFIX}_" || echo "")
    if [ -z "$active_sessions" ]; then
        echo "No active sessions found"
    else
        echo "$active_sessions"
        echo ""
        echo "Active count: $(echo "$active_sessions" | wc -l)"
    fi
    
    echo ""
    echo "📊 Status summary:"
    if [ -f logs/active_sessions.txt ]; then
        local running_count=0
        local completed_count=0
        local failed_count=0
        
        while IFS=':' read -r session_name status_file; do
            if [ -f "$status_file" ]; then
                local status=$(cat "$status_file" 2>/dev/null)
                case "$status" in
                    "RUNNING") ((running_count++)) ;;
                    "COMPLETED_SUCCESS"|"FINISHED") ((completed_count++)) ;;
                    "COMPLETED_FAILED") ((failed_count++)) ;;
                esac
            fi
        done < logs/active_sessions.txt
        
        echo "  Running: $running_count"
        echo "  Completed: $completed_count"
        echo "  Failed: $failed_count"
    fi
    
    echo ""
    echo "💡 To attach to a session, use: tmux attach-session -t <session_name>"
    echo "💡 To detach from a session, press: Ctrl+b then d"
    echo "💡 To list all sessions: tmux list-sessions"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# Initialize session tracking file
mkdir -p logs
> logs/active_sessions.txt

# Determine which challenges to run
if [ -z "$START_INDEX" ]; then
    # No specific index provided, run all challenges
    echo "No specific index provided. Running all challenges $TRY_TIMES time(s) each with $PARALLEL_TASKS parallel task(s)."
    # Get all challenge IDs and their paths from the JSON file
    challenges=$(jq -r 'to_entries[] | [.key, .value.path] | @tsv' "$DATASET_JSON")
elif [ -z "$END_INDEX" ]; then
    # Only start index provided - run a single challenge
    # Check if the index is a number
    if ! [[ "$START_INDEX" =~ ^[0-9]+$ ]]; then
        echo "Error: Index must be a number"
        echo "Usage: $0 [start_index] [end_index] [try_times] [parallel_tasks]"
        exit 1
    fi

    # Get all challenges first
    all_challenges=$(jq -r 'to_entries[] | [.key, .value.path] | @tsv' "$DATASET_JSON")
    
    # Count the total number of challenges
    total_challenges=$(echo "$all_challenges" | wc -l)
    
    if [ "$START_INDEX" -lt 1 ] || [ "$START_INDEX" -gt "$total_challenges" ]; then
        echo "Error: Index out of range. Valid range is 1-$total_challenges"
        exit 1
    fi
    
    # Get the challenge at the specified index (using sed to extract the line)
    challenges=$(echo "$all_challenges" | sed -n "${START_INDEX}p")
    
    # Get the challenge ID for display
    challenge_id=$(echo "$challenges" | cut -f1)
    echo "Running challenge at index $START_INDEX: $challenge_id ($TRY_TIMES time(s)) with $PARALLEL_TASKS parallel task(s)"
else
    # Both start and end indexes provided - run a range of challenges
    # Check if both indexes are numbers
    if ! [[ "$START_INDEX" =~ ^[0-9]+$ ]] || ! [[ "$END_INDEX" =~ ^[0-9]+$ ]]; then
        echo "Error: Indexes must be numbers"
        echo "Usage: $0 [start_index] [end_index] [try_times] [parallel_tasks]"
        exit 1
    fi

    # Get all challenges first
    all_challenges=$(jq -r 'to_entries[] | [.key, .value.path] | @tsv' "$DATASET_JSON")
    
    # Count the total number of challenges
    total_challenges=$(echo "$all_challenges" | wc -l)
    
    # Validate indexes
    if [ "$START_INDEX" -lt 1 ] || [ "$START_INDEX" -gt "$total_challenges" ]; then
        echo "Error: Start index out of range. Valid range is 1-$total_challenges"
        exit 1
    fi
    
    if [ "$END_INDEX" -lt 1 ] || [ "$END_INDEX" -gt "$total_challenges" ]; then
        echo "Error: End index out of range. Valid range is 1-$total_challenges"
        exit 1
    fi
    
    if [ "$START_INDEX" -gt "$END_INDEX" ]; then
        echo "Error: Start index cannot be greater than end index"
        exit 1
    fi
    
    # Get the challenges in the specified range
    challenges=$(echo "$all_challenges" | sed -n "${START_INDEX},${END_INDEX}p")
    
    echo "Running challenges from index $START_INDEX to $END_INDEX ($TRY_TIMES time(s) each) with $PARALLEL_TASKS parallel task(s)"
fi

# Initialize counters
total_jobs=0
completed_jobs=0
failed_jobs=0
start_time=$(date +%s)

echo ""
echo "🚀 Starting parallel execution in tmux sessions..."
echo "📊 You can attach to any session to monitor progress"
echo ""

# Process each challenge
instance_id=0
while IFS=$'\t' read -r challenge_id challenge_path; do
    if [ -z "$challenge_path" ]; then
        continue
    fi
    
    # Run the challenge multiple times based on TRY_TIMES
    for try_num in $(seq 1 $TRY_TIMES); do
        # Wait for a slot to become available
        wait_for_slot
        
        # Increment counters
        ((total_jobs++))
        ((instance_id++))
        
        # Run challenge in tmux session
        run_challenge "$challenge_id" "$challenge_path" "$try_num" "$instance_id"
        
        # Small delay to avoid overwhelming the system
        sleep 10
    done
    
    # Show active sessions every 5 challenges
    if [ $((instance_id % 5)) -eq 0 ]; then
        show_active_sessions
    fi
done <<< "$challenges"

echo "📋 All $total_jobs job(s) have been started in tmux sessions"
show_active_sessions

# Monitor sessions and wait for completion
echo "⏳ Monitoring tmux sessions for completion..."
monitor_start_time=$(date +%s)

while true; do
    # Clean up finished sessions first
    cleanup_finished_sessions
    
    # Count active sessions
    active_count=$(get_active_session_count)
    
    if [ $active_count -eq 0 ]; then
        echo "🏁 All sessions completed!"
        break
    fi
    
    # Show progress every 30 seconds
    current_time=$(date +%s)
    elapsed=$((current_time - monitor_start_time))
    
    if [ $((elapsed % 30)) -eq 0 ] || [ $elapsed -lt 30 ]; then
        echo "📈 Still running: $active_count tmux sessions active (${elapsed}s elapsed)"
        
        # Show detailed status every 60 seconds
        if [ $((elapsed % 60)) -eq 0 ] && [ $elapsed -gt 0 ]; then
            show_active_sessions
        fi
    fi
    
    sleep 5
done

# Count results from status files
successful_jobs=0
failed_jobs=0
completed_jobs=0

for status_file in logs/status_*.txt; do
    if [ -f "$status_file" ]; then
        ((completed_jobs++))
        status=$(cat "$status_file" 2>/dev/null)
        case "$status" in
            "COMPLETED_SUCCESS"|"FINISHED")
                ((successful_jobs++))
                ;;
            "COMPLETED_FAILED")
                ((failed_jobs++))
                ;;
        esac
    fi
done

# Calculate execution time
end_time=$(date +%s)
execution_time=$((end_time - start_time))

# Final summary
echo ""
echo "================================================================="
echo "🏁 EXECUTION SUMMARY"
echo "================================================================="
echo "Total jobs: $total_jobs"
echo "Completed: $completed_jobs"
echo "Successful: $successful_jobs"
echo "Failed: $failed_jobs"
echo "Execution time: ${execution_time}s"
echo "Parallel tasks: $PARALLEL_TASKS"

if [ $failed_jobs -eq 0 ]; then
    echo "🎉 All challenges completed successfully!"
    exit 0
else
    echo "⚠️  Some challenges failed. Check individual log files in the logs/ directory."
    exit 1
fi 