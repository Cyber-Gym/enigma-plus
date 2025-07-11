#!/bin/bash

# CRITICAL FIX: Ensure script runs from the correct directory
cd "$(dirname "${BASH_SOURCE[0]}")"

DATASET_NAME=$1
# CRITICAL FIX: Use absolute path for consistency
SCRIPT_DIR="$(pwd)"
DATASET_JSON="$(cd "$SCRIPT_DIR/../NYU_CTF_Bench" && pwd)/${DATASET_NAME}.json"
MODEL_NAME="bedrock:us.anthropic.claude-3-5-sonnet-20241022-v2:0"
IMAGE_NAME="sweagent/enigma:latest"
CONFIG_FILE="config/default_ctf.yaml"
HOST_URL="http://localhost:8000"
OPENAI_API_KEY="dummy"
OPENAI_API_BASE_URL="http://localhost:30000/v1"
PER_INSTANCE_STEP_LIMIT=40
export SWE_AGENT_ACTION_TIMEOUT=20

# Generate a unique identifier for this execution session
# This prevents conflicts when running on multiple machines
MACHINE_ID=$(hostname)
PROCESS_ID=$$
TIMESTAMP=$(date +%s)
EXECUTION_ID="${MACHINE_ID}_${PROCESS_ID}_${TIMESTAMP}"

echo "🆔 Execution ID: $EXECUTION_ID"
echo "   This ensures no conflicts with other machines/processes"

# Extract base name from DATASET_JSON for trajectory_path
DATASET_BASE_NAME=$(basename "$DATASET_JSON" .json)

# export SWE_AGENT_ACTION_TIMEOUT=60
# Check if indexes were provided
START_INDEX=$2
END_INDEX=$3
TRY_TIMES=$4
PARALLEL_TASKS=25
DISABLE_CLEANUP=false

# Set default values
if [ -z "$TRY_TIMES" ]; then
    TRY_TIMES=1
else
    # Validate that TRY_TIMES is a positive number
    if ! [[ "$TRY_TIMES" =~ ^[0-9]+$ ]] || [ "$TRY_TIMES" -lt 1 ]; then
        echo "Error: Try times must be a positive number"
        echo "Usage: $0 <dataset_name> [start_index] [end_index] [try_times] [parallel_tasks] [disable_cleanup]"
        exit 1
    fi
fi

if [ -z "$PARALLEL_TASKS" ]; then
    PARALLEL_TASKS=1
else
    # Validate that PARALLEL_TASKS is a positive number
    if ! [[ "$PARALLEL_TASKS" =~ ^[0-9]+$ ]] || [ "$PARALLEL_TASKS" -lt 1 ]; then
        echo "Error: Parallel tasks must be a positive number"
        echo "Usage: $0 <dataset_name> [start_index] [end_index] [try_times] [parallel_tasks] [disable_cleanup]"
        exit 1
    fi
fi

if [ -z "$DISABLE_CLEANUP" ]; then
    DISABLE_CLEANUP=false
else
    # Validate that DISABLE_CLEANUP is a boolean-like value
    case "$DISABLE_CLEANUP" in
        true|TRUE|1|yes|YES)
            DISABLE_CLEANUP=true
            ;;
        false|FALSE|0|no|NO)
            DISABLE_CLEANUP=false
            ;;
        *)
            echo "Error: disable_cleanup must be true/false, 1/0, yes/no"
            echo "Usage: $0 <dataset_name> [start_index] [end_index] [try_times] [parallel_tasks] [disable_cleanup]"
            exit 1
            ;;
    esac
fi

echo "Configuration:"
echo "  Try times per challenge: $TRY_TIMES"
echo "  Parallel tasks: $PARALLEL_TASKS"
echo "  Disable cleanup: $DISABLE_CLEANUP"
echo "  Model: $MODEL_NAME"
echo "  Image: $IMAGE_NAME"

# Clean up Docker networks/subnets first thing when starting the script
if [ "$DISABLE_CLEANUP" = false ]; then
    echo ""
    echo "🧹 Comprehensive Docker cleanup before starting..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Step 1: Stop and remove ALL non-essential containers first
    echo "🔍 Step 1: Stopping and removing non-essential containers..."
    
    # Get all containers that are NOT based on lmsysorg/sglang (preserve the LLM server)
    all_containers=$(docker ps -a --format "{{.ID}}\t{{.Image}}\t{{.Names}}" | grep -v "lmsysorg/sglang" | grep -v "CONTAINER\sID" || true)
    
    if [ -n "$all_containers" ]; then
        echo "Found containers to remove (preserving lmsysorg/sglang):"
        echo "$all_containers"
        
        # Extract container IDs and stop them in batches
        container_ids=$(echo "$all_containers" | awk '{print $1}' | tr '\n' ' ')
        
        if [ -n "$container_ids" ]; then
            echo "  🛑 Stopping containers..."
            docker stop $container_ids 2>/dev/null || true
            
            # Wait a moment for graceful shutdown
            sleep 3
            
            echo "  🗑️  Removing containers..."
            docker rm -f $container_ids 2>/dev/null || true
            
            # Additional cleanup for containers that might still be running
            echo "  🔄 Force removing any remaining containers..."
            docker ps -a --format "{{.ID}}" | grep -v "CONTAINER" | while read -r container_id; do
                if [ -n "$container_id" ]; then
                    # Check if it's not an lmsysorg/sglang container
                    image_name=$(docker inspect "$container_id" --format "{{.Config.Image}}" 2>/dev/null || echo "")
                    if [[ "$image_name" != *"lmsysorg/sglang"* ]]; then
                        echo "    Force removing container: $container_id ($image_name)"
                        docker rm -f "$container_id" 2>/dev/null || true
                    fi
                fi
            done
        fi
        
        echo "  ✅ Container cleanup completed"
    else
        echo "  ℹ️  No non-essential containers found"
    fi

    # Step 2: Clean up ALL CTF-related and custom networks
    echo ""
    echo "🔍 Step 2: Cleaning up CTF-related and custom networks..."
    
    # IMPROVED: Faster network cleanup with parallel processing
    echo "  🌐 Fast cleanup of CTF networks..."
    
    # Get all CTF-related networks in one go
    custom_networks=$(docker network ls --format "{{.Name}}" | grep -E "(ctfnet|_default|tmp_ctfnet)$" || true)
    
    if [ -n "$custom_networks" ]; then
        echo "Found networks to clean up:"
        echo "$custom_networks"
        
        # First, disconnect all containers from all networks in parallel
        echo "  🔌 Mass disconnecting containers from networks..."
        echo "$custom_networks" | xargs -P 8 -I {} sh -c '
            network="$1"
            containers=$(docker network inspect "$network" --format "{{range .Containers}}{{.Name}} {{end}}" 2>/dev/null || true)
            if [ -n "$containers" ]; then
                echo "    Disconnecting from $network"
                echo "$containers" | xargs -r docker network disconnect -f "$network" 2>/dev/null || true
            fi
        ' -- {}
        
        # Brief pause to let disconnections complete
        sleep 1
        
        # Remove all networks in parallel
        echo "  🗑️  Removing networks in parallel..."
        echo "$custom_networks" | xargs -P 8 docker network rm 2>/dev/null || true
        
        # Quick final cleanup for any stubborn networks
        remaining_networks=$(docker network ls --format "{{.Name}}" | grep -E "(ctfnet|_default|tmp_ctfnet)$" || true)
        if [ -n "$remaining_networks" ]; then
            echo "  🧹 Final cleanup of remaining networks..."
            echo "$remaining_networks" | xargs -r docker network rm 2>/dev/null || true
        fi
        
        echo "  ✅ Network cleanup completed"
    else
        echo "  ℹ️  No CTF-related networks found"
    fi

    # Step 3: Prune unused Docker resources
    echo ""
    echo "🔍 Step 3: Pruning unused Docker resources..."
    
    # Prune networks (removes unused networks)
    echo "  🌐 Pruning unused networks..."
    docker network prune -f 2>/dev/null || true
    
    # Prune volumes (removes unused volumes)
    echo "  💾 Pruning unused volumes..."
    docker volume prune -f 2>/dev/null || true
    
    # Show remaining resources for verification
    echo ""
    echo "📊 Remaining Docker resources after cleanup:"
    echo "  Containers:"
    container_count=$(docker ps -a --format "{{.Names}}\t{{.Image}}\t{{.Status}}" | wc -l)
    if [ "$container_count" -gt 0 ]; then
        docker ps -a --format "    {{.Names}}\t{{.Image}}\t{{.Status}}" | head -5
        if [ "$container_count" -gt 5 ]; then
            echo "    ... and $((container_count - 5)) more"
        fi
    else
        echo "    No containers found"
    fi
    
    echo "  Networks:"
    network_count=$(docker network ls --format "{{.Name}}\t{{.Driver}}" | grep -v "NETWORK" | wc -l)
    if [ "$network_count" -gt 0 ]; then
        docker network ls --format "    {{.Name}}\t{{.Driver}}"
    else
        echo "    Only default networks found"
    fi

    echo ""
    echo "✅ Comprehensive initial cleanup completed"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
else
    echo ""
    echo "🚫 Cleanup disabled - skipping initial Docker cleanup"
    echo ""
fi

# Session name prefix for tmux sessions - now machine-specific
SESSION_PREFIX="swe_agent_${EXECUTION_ID}"

# Machine-specific tracking files
ACTIVE_SESSIONS_FILE="logs/active_sessions_${EXECUTION_ID}.txt"
STATUS_FILE_PREFIX="logs/status_${EXECUTION_ID}"

# Function to check if session exists and is active
session_exists() {
    local session_name=$1
    tmux has-session -t "$session_name" 2>/dev/null
}

# Function to get active session count for this execution only
get_active_session_count() {
    tmux list-sessions 2>/dev/null | grep "^${SESSION_PREFIX}_" | wc -l
}

# Function to run a single challenge in a tmux session
run_challenge() {
    local challenge_id=$1
    local challenge_path=$2
    local try_num=$3
    local instance_id=$4
    
    # CRITICAL FIX: Use absolute paths to prevent path duplication
    # Get the absolute path to the workspace root
    local WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local CTF_BENCH_ROOT="$(cd "$WORKSPACE_ROOT/../NYU_CTF_Bench" && pwd)"
    
    # Construct absolute paths
    local DATA_PATH="${CTF_BENCH_ROOT}/${challenge_path}/challenge.json"
    local REPO_PATH="${CTF_BENCH_ROOT}/${challenge_path}/"
    
    # Create unique session name with execution ID
    local session_name="${SESSION_PREFIX}_${instance_id}_${challenge_id}_try${try_num}"
    
    # Create unique log files for each parallel instance - machine-specific
    local LOG_PREFIX="logs/${EXECUTION_ID}_parallel_${instance_id}_${challenge_id}_try${try_num}"
    local STATUS_FILE="${STATUS_FILE_PREFIX}_${instance_id}_${challenge_id}_try${try_num}.txt"
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
    
    # CRITICAL FIX: Add immediate cleanup mechanism using trap in tmux session
    # Create the tmux session with improved command structure and immediate cleanup
    tmux new-session -d -s "$session_name" -c "$WORKSPACE_ROOT" \
    bash -c "
        # CRITICAL FIX: Set up immediate cleanup on session exit
        container_name=\"${EXECUTION_ID}-parallel-${instance_id}-${challenge_id}-try${try_num}\"
        
        cleanup_immediately() {
            echo 'Performing immediate cleanup for: $challenge_id (try $try_num)' | tee -a '${LOG_PREFIX}.log'
            
            # Mark as finished first
            echo 'FINISHED' > '$STATUS_FILE'
            
            # Clean up the specific container immediately
            if docker ps -a --format '{{.Names}}' | grep -q \"^\$container_name\$\"; then
                echo '  🐳 Removing container: '\$container_name | tee -a '${LOG_PREFIX}.log'
                docker stop \"\$container_name\" 2>/dev/null || true
                docker rm \"\$container_name\" 2>/dev/null || true
                sleep 1
            fi
            
            # Clean up networks associated with this specific task
            task_networks=\$(docker network ls --format '{{.Name}}' | grep -E '(ctfnet.*${challenge_id}|tmp_ctfnet.*${challenge_id}|${EXECUTION_ID}.*${challenge_id})' || true)
            
            if [ -n \"\$task_networks\" ]; then
                echo '  🌐 Cleaning up task-specific networks:' | tee -a '${LOG_PREFIX}.log'
                echo \"\$task_networks\" | while read -r network_name; do
                    if [ -n \"\$network_name\" ]; then
                        echo '    Removing network: '\$network_name | tee -a '${LOG_PREFIX}.log'
                        
                        # Force disconnect any remaining containers
                        docker network inspect \"\$network_name\" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | \\
                        while read -r container; do
                            if [ -n \"\$container\" ] && [ \"\$container\" != '<no value>' ]; then
                                echo '      Disconnecting container '\$container' from '\$network_name | tee -a '${LOG_PREFIX}.log'
                                docker network disconnect \"\$network_name\" \"\$container\" -f 2>/dev/null || true
                            fi
                        done
                        
                        # Remove the network
                        docker network rm \"\$network_name\" 2>/dev/null || true
                    fi
                done
            fi
            
            echo '  ✅ Immediate cleanup completed for: $challenge_id (try $try_num)' | tee -a '${LOG_PREFIX}.log'
        }
        
        # Set up trap to ensure cleanup happens on ANY exit (success, failure, or interrupt)
        trap cleanup_immediately EXIT
        
        echo 'Starting challenge: $challenge_id (try $try_num)' | tee -a '${LOG_PREFIX}.log'
        echo 'RUNNING' > '$STATUS_FILE'

        # Run the main command and capture exit code
        export OPENAI_API_KEY=\"\$OPENAI_API_KEY\"
        export OPENAI_API_BASE_URL=\"\$OPENAI_API_BASE_URL\"
        python run.py \\
            --model_name '$MODEL_NAME' \\
            --ctf \\
            --image_name \"$IMAGE_NAME\" \\
            --data_path \"$DATA_PATH\" \\
            --repo_path \"$REPO_PATH\" \\
            --config_file \"$CONFIG_FILE\" \\
            --host_url \"$HOST_URL\" \\
            --per_instance_step_limit $PER_INSTANCE_STEP_LIMIT \\
            --trajectory_path \"trajectories/$DATASET_BASE_NAME/try${try_num}\" \\
            --temperature=0 \\
            --top_p=0.95 \\
            --enable_dynamic_ports \\
            --container_name \"\$container_name\" \\
            --allow_dirty_repo \\
            2>&1 | tee -a '${LOG_PREFIX}.log'
        
        exit_code=\$?
        
        # Update status based on exit code (before cleanup trap runs)
        if [ \$exit_code -eq 0 ]; then
            echo 'COMPLETED_SUCCESS' > '$STATUS_FILE'
            echo 'Challenge completed successfully: $challenge_id (try $try_num)' | tee -a '${LOG_PREFIX}.log'
        else
            echo 'COMPLETED_FAILED' > '$STATUS_FILE'
            echo 'Challenge failed: $challenge_id (try $try_num) - Exit code: '\$exit_code | tee -a '${LOG_PREFIX}.log'
        fi
        
        echo 'Session will close in 1 second...' | tee -a '${LOG_PREFIX}.log'
        sleep 1
        
        # Exit will trigger the cleanup trap
        exit \$exit_code
    "
    
    # Store session info for tracking - use machine-specific file
    echo "${session_name}:${STATUS_FILE}" >> "$ACTIVE_SESSIONS_FILE"
    
    return 0
}

# Function to wait for previous try of the same challenge to finish
wait_for_previous_try() {
    local challenge_id=$1
    local try_num=$2
    
    # If this is try 1, no need to wait
    if [ "$try_num" -eq 1 ]; then
        return 0
    fi
    
    local previous_try=$((try_num - 1))
    
    echo "⏳ [Challenge: $challenge_id] Waiting for try $previous_try to finish before starting try $try_num..."
    
    while true; do
        # Look for any active sessions for this challenge with the previous try number
        local previous_session_active=false
        
        if [ -f "$ACTIVE_SESSIONS_FILE" ]; then
            while IFS=':' read -r session_name status_file; do
                # Check if this session is for the same challenge and previous try
                if echo "$session_name" | grep -q "${SESSION_PREFIX}_[0-9]*_${challenge_id}_try${previous_try}"; then
                    if [ -f "$status_file" ]; then
                        local status=$(cat "$status_file" 2>/dev/null)
                        case "$status" in
                            "RUNNING")
                                previous_session_active=true
                                break
                                ;;
                            "COMPLETED_SUCCESS"|"COMPLETED_FAILED"|"FINISHED")
                                # Previous try is done
                                ;;
                        esac
                    fi
                fi
            done < "$ACTIVE_SESSIONS_FILE"
        fi
        
        if [ "$previous_session_active" = false ]; then
            echo "✅ [Challenge: $challenge_id] Try $previous_try finished, starting try $try_num"
            break
        fi
        
        sleep 2
    done
}

# Function to clean up resources for a specific completed task
cleanup_task_resources() {
    local challenge_id=$1
    local try_num=$2
    local instance_id=$3
    
    if [ "$DISABLE_CLEANUP" = true ]; then
        echo "🚫 Task cleanup disabled - skipping cleanup for challenge: $challenge_id (try $try_num)"
        return
    fi
    
    echo "🧹 Cleaning up resources for completed task: $challenge_id (try $try_num)"
    
    # Build the container name pattern for this specific task
    local container_pattern="${EXECUTION_ID}-parallel-${instance_id}-${challenge_id}-try${try_num}"
    # Build network patterns for this specific task
    local network_patterns=(
        "ctfnet.*${challenge_id}.*try${try_num}"
        "tmp_ctfnet.*${challenge_id}.*try${try_num}"
        "${challenge_id}.*try${try_num}.*_default"
        "${EXECUTION_ID}.*${challenge_id}.*try${try_num}"
    )
    
    # Clean up task-specific containers
    echo "  🐳 Cleaning up containers for task..."
    task_containers=$(docker ps -a --format "{{.Names}}" | grep "^${container_pattern}$" || true)
    if [ -n "$task_containers" ]; then
        echo "    Found containers to remove:"
        echo "$task_containers" | while read -r container; do
            echo "      Stopping container: $container"
            docker stop "$container" 2>/dev/null || true
            echo "      Removing container: $container"
            docker rm -f "$container" 2>/dev/null || true
        done
    else
        echo "    No task-specific containers found"
    fi
    
    # Clean up task-specific networks
    echo "  🌐 Cleaning up networks for task..."
    for pattern in "${network_patterns[@]}"; do
        task_networks=$(docker network ls --format "{{.Name}}" | grep -E "$pattern" || true)
        if [ -n "$task_networks" ]; then
            echo "    Found networks matching pattern '$pattern':"
            echo "$task_networks" | while read -r network; do
                echo "      Processing network: $network"
                # Get and disconnect all containers from this network
                connected_containers=$(docker network inspect "$network" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || true)
                if [ -n "$connected_containers" ]; then
                    echo "        Disconnecting containers..."
                    for container in $connected_containers; do
                        echo "          Disconnecting: $container"
                        docker network disconnect -f "$network" "$container" 2>/dev/null || true
                    done
                fi
                echo "        Removing network: $network"
                docker network rm "$network" 2>/dev/null || true
            done
        fi
    done
    
    echo "  ✅ Task-specific cleanup completed"
}

# Function to clean up finished sessions
cleanup_finished_sessions() {
    if [ ! -f "$ACTIVE_SESSIONS_FILE" ]; then
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
                    
                    # Extract task details from session name for cleanup
                    # Session name format: swe_agent_${instance_id}_${challenge_id}_try${try_num}
                    if [[ "$session_name" =~ ^${SESSION_PREFIX}_([0-9]+)_(.+)_try([0-9]+)$ ]]; then
                        local instance_id="${BASH_REMATCH[1]}"
                        local challenge_id="${BASH_REMATCH[2]}"
                        local try_num="${BASH_REMATCH[3]}"
                        
                        echo "  📋 Extracted task details: instance_id=$instance_id, challenge_id=$challenge_id, try_num=$try_num"
                        
                        # Clean up task-specific Docker resources (backup cleanup)
                        cleanup_task_resources "$challenge_id" "$try_num" "$instance_id"
                    else
                        echo "  ⚠️  Could not extract task details from session name: $session_name"
                    fi
                    
                    # Kill the tmux session
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
    done < "$ACTIVE_SESSIONS_FILE"
    
    # Replace active sessions file
    mv "$temp_file" "$ACTIVE_SESSIONS_FILE"
}

# Function to clean up orphaned resources from this execution
cleanup_orphaned_resources() {
    if [ "$DISABLE_CLEANUP" = true ]; then
        return
    fi
    
    echo "🧹 Checking for orphaned Docker resources from this execution..."
    
    # Get list of active tmux sessions for this execution
    local active_sessions=$(tmux list-sessions 2>/dev/null | grep "^${SESSION_PREFIX}_" | cut -d: -f1 || true)
    
    # Clean up containers from this execution that may have been missed
    orphaned_containers=$(docker ps -a --format "{{.Names}}" | grep "^${EXECUTION_ID}-parallel-" || true)
    if [ -n "$orphaned_containers" ]; then
        echo "  🐳 Found containers from this execution, checking if they're orphaned..."
        
        # OPTIMIZED: Check and cleanup containers in parallel for faster processing
        echo "$orphaned_containers" | xargs -P 8 -I {} bash -c '
            container_name="$1"
            active_sessions="$2"
            EXECUTION_ID="$3"
            SESSION_PREFIX="$4"
            
            if [ -n "$container_name" ]; then
                # Extract instance_id and challenge_id from container name
                # Container format: ${EXECUTION_ID}-parallel-${instance_id}-${challenge_id}-try${try_num}
                if [[ "$container_name" =~ ^${EXECUTION_ID}-parallel-([0-9]+)-(.+)-try([0-9]+)$ ]]; then
                    instance_id="${BASH_REMATCH[1]}"
                    challenge_id="${BASH_REMATCH[2]}"
                    try_num="${BASH_REMATCH[3]}"
                    
                    # Check if there'"'"'s an active tmux session for this container
                    expected_session_name="${SESSION_PREFIX}_${instance_id}_${challenge_id}_try${try_num}"
                    
                    session_is_active=false
                    if [ -n "$active_sessions" ]; then
                        while IFS= read -r session_name; do
                            if [ "$session_name" = "$expected_session_name" ]; then
                                session_is_active=true
                                break
                            fi
                        done <<< "$active_sessions"
                    fi
                    
                    if [ "$session_is_active" = false ]; then
                        echo "    🗑️  Removing orphaned container: $container_name (no active session)"
                        docker stop "$container_name" 2>/dev/null || true
                        docker rm -f "$container_name" 2>/dev/null || true
                    fi
                else
                    echo "    ⚠️  Container name doesn'"'"'t match expected pattern: $container_name"
                fi
            fi
        ' -- {} "$active_sessions" "$EXECUTION_ID" "$SESSION_PREFIX"
    fi
    
    # Clean up networks from this execution
    orphaned_networks=$(docker network ls --format "{{.Name}}" | grep -E "(${EXECUTION_ID}|ctfnet.*$(echo ${EXECUTION_ID} | cut -d'_' -f2))" || true)
    if [ -n "$orphaned_networks" ]; then
        echo "  🌐 Found orphaned networks:"
        echo "$orphaned_networks"
        
        # OPTIMIZED: Process networks in parallel for faster cleanup
        echo "$orphaned_networks" | xargs -P 8 -I {} bash -c '
            network_name="$1"
            if [ -n "$network_name" ]; then
                echo "    Processing network: $network_name"
                # Force disconnect any containers first
                connected_containers=$(docker network inspect "$network_name" --format '"'"'{{range .Containers}}{{.Name}} {{end}}'"'"' 2>/dev/null || true)
                if [ -n "$connected_containers" ]; then
                    for container in $connected_containers; do
                        echo "      Disconnecting: $container"
                        docker network disconnect -f "$network_name" "$container" 2>/dev/null || true
                    done
                fi
                echo "      Removing network: $network_name"
                docker network rm "$network_name" 2>/dev/null || true
            fi
        ' -- {}
    fi
    
    echo "  ✅ Orphaned resource cleanup completed"
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
        
        # CRITICAL FIX: Also run orphaned resource cleanup every few iterations
        # to catch any resources that might have been missed
        if [ $((active_count % 10)) -eq 0 ]; then
            cleanup_orphaned_resources
        fi
        
        sleep 1
    done
}

# Function to clean up all tmux sessions on exit
cleanup() {
    if [ "$DISABLE_CLEANUP" = true ]; then
        echo "🚫 Cleanup disabled - skipping cleanup operations"
        return
    fi
    
    echo ""
    echo "🛑 Starting comprehensive cleanup process..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Step 1: Clean up tmux sessions
    echo "🔍 Step 1: Cleaning up tmux sessions..."
    
    # Kill all sessions with our prefix
    tmux_sessions=$(tmux list-sessions 2>/dev/null | grep "^${SESSION_PREFIX}_" | cut -d: -f1 || true)
    if [ -n "$tmux_sessions" ]; then
        echo "Found tmux sessions to cleanup:"
        echo "$tmux_sessions"
        
        # OPTIMIZED: Kill sessions in parallel (much faster)
        echo "  🛑 Killing sessions in parallel..."
        echo "$tmux_sessions" | xargs -P 10 -I {} tmux kill-session -t {} 2>/dev/null || true
        
        echo "  ✅ Tmux session cleanup completed"
    else
        echo "  ℹ️  No tmux sessions found with prefix: ${SESSION_PREFIX}_"
    fi
    
    # Step 2: Clean up tracking files
    echo ""
    echo "🔍 Step 2: Cleaning up tracking files..."
    
    # Clean up tracking files - only remove files for this execution
    files_removed=0
    if [ -f "$ACTIVE_SESSIONS_FILE" ]; then
        rm -f "$ACTIVE_SESSIONS_FILE" && ((files_removed++))
    fi
    
    # Remove status files for this execution
    for status_file in "${STATUS_FILE_PREFIX}"*.txt; do
        if [ -f "$status_file" ]; then
            rm -f "$status_file" && ((files_removed++))
        fi
    done
    
    if [ $files_removed -gt 0 ]; then
        echo "  ✅ Removed $files_removed tracking files"
    else
        echo "  ℹ️  No tracking files found to remove"
    fi

    # Step 3: Clean up Docker containers
    echo ""
    echo "🔍 Step 3: Cleaning up Docker containers..."
    
    # Get all container IDs that are NOT based on lmsysorg/sglang images
    containers_to_remove=$(docker ps -a --format "table {{.ID}}\t{{.Image}}" | grep -v "lmsysorg/sglang" | grep -v "CONTAINER ID" | awk '{print $1}' || true)
    
    if [ -n "$containers_to_remove" ]; then
        echo "Found containers to remove (preserving lmsysorg/sglang):"
        # Show which containers will be removed
        docker ps -a --format "table {{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}" | head -1
        docker ps -a --format "table {{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}" | grep -v "lmsysorg/sglang" | grep -v "CONTAINER ID" || true
        
        # OPTIMIZED: Stop containers in parallel (much faster)
        echo "  🛑 Stopping containers in parallel..."
        echo "$containers_to_remove" | xargs -P 10 -I {} docker stop {} 2>/dev/null || true
        
        # Brief wait for graceful shutdown
        sleep 2
        
        # OPTIMIZED: Remove containers in parallel (much faster)
        echo "  🗑️  Removing containers in parallel..."
        echo "$containers_to_remove" | xargs -P 10 -I {} docker rm -f {} 2>/dev/null || true
        
        echo "  ✅ Docker container cleanup completed"
    else
        echo "  ℹ️  No containers to remove (all remaining containers are based on lmsysorg/sglang or no containers found)"
    fi
    
    # Step 4: Clean up Docker networks
    echo ""
    echo "🔍 Step 4: Cleaning up Docker networks..."
    
    # Clean up ALL custom networks (preserving default bridge, host, none)
    custom_networks=$(docker network ls --format "{{.Name}}" | grep -v -E "^(bridge|host|none)$" || true)
    if [ -n "$custom_networks" ]; then
        echo "Found custom networks to remove:"
        echo "$custom_networks"
        
        # OPTIMIZED: Process networks in parallel for faster cleanup
        echo "  🌐 Processing networks in parallel..."
        echo "$custom_networks" | xargs -P 8 -I {} bash -c '
            network_name="$1"
            if [ -n "$network_name" ]; then
                echo "    Processing network: $network_name"
                
                # Check if network still exists
                if docker network inspect "$network_name" >/dev/null 2>&1; then
                    # First try to disconnect any remaining containers
                    connected_containers=$(docker network inspect "$network_name" --format '"'"'{{range .Containers}}{{.Name}} {{end}}'"'"' 2>/dev/null | tr '"'"' '"'"' '"'"'\n'"'"' | grep -v "^$" || true)
                    
                    if [ -n "$connected_containers" ]; then
                        echo "      📋 Disconnecting containers from network..."
                        echo "$connected_containers" | while read -r container_name; do
                            if [ -n "$container_name" ] && [ "$container_name" != "<no value>" ]; then
                                # Check if it'"'"'s an lmsysorg/sglang container
                                image_name=$(docker inspect "$container_name" --format "{{.Config.Image}}" 2>/dev/null || echo "")
                                if [[ "$image_name" == *"lmsysorg/sglang"* ]]; then
                                    echo "        ⚠️  Preserving lmsysorg/sglang container: $container_name"
                                    continue
                                fi
                                
                                echo "        🔌 Disconnecting container $container_name from $network_name"
                                docker network disconnect "$network_name" "$container_name" -f 2>/dev/null || true
                            fi
                        done
                        
                        # Brief wait for disconnections to be processed
                        sleep 1
                    fi
                    
                    # Now remove the network
                    echo "      🗑️  Removing network: $network_name"
                    if docker network rm "$network_name" 2>/dev/null; then
                        echo "      ✅ Successfully removed network: $network_name"
                    else
                        echo "      ⚠️  Failed to remove network: $network_name (may still have dependencies)"
                    fi
                else
                    echo "      ℹ️  Network $network_name no longer exists"
                fi
            fi
        ' -- {}
        
        echo "  ✅ Network cleanup completed"
    else
        echo "  ℹ️  No custom networks found"
    fi
    
    # Step 5: Prune unused resources
    echo ""
    echo "🔍 Step 5: Pruning unused Docker resources..."
    
    # Prune all unused networks to free up subnet space completely
    echo "  🌐 Pruning all unused Docker networks..."
    docker network prune -f 2>/dev/null || true
    
    # Prune unused volumes
    echo "  💾 Pruning unused volumes..."
    docker volume prune -f 2>/dev/null || true

    # Step 6: Clean up temporary files
    echo ""
    echo "🔍 Step 6: Cleaning up temporary files..."
    
    temp_files_removed=0
    for temp_file in /tmp/docker-compose-* docker-compose-* ./docker-compose-*; do
        if [ -f "$temp_file" ]; then
            rm -f "$temp_file" 2>/dev/null && ((temp_files_removed++)) || true
        fi
    done
    
    if [ $temp_files_removed -gt 0 ]; then
        echo "  ✅ Removed $temp_files_removed temporary docker-compose files"
    else
        echo "  ℹ️  No temporary docker-compose files found"
    fi
    
    # Final verification
    echo ""
    echo "📊 Final cleanup verification:"
    echo "  Remaining containers:"
    remaining_containers=$(docker ps -a --format "{{.Names}}\t{{.Image}}" | wc -l)
    if [ "$remaining_containers" -gt 0 ]; then
        docker ps -a --format "    {{.Names}}\t{{.Image}}" | head -3
        if [ "$remaining_containers" -gt 3 ]; then
            echo "    ... and $((remaining_containers - 3)) more"
        fi
    else
        echo "    No containers found"
    fi
    
    echo "  Remaining networks:"
    docker network ls --format "    {{.Name}}\t{{.Driver}}"
    
    echo ""
    echo "✅ Comprehensive cleanup completed successfully"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
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
    if [ -f "$ACTIVE_SESSIONS_FILE" ]; then
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
        done < "$ACTIVE_SESSIONS_FILE"
        
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
> "$ACTIVE_SESSIONS_FILE"

# Proactive cleanup of leftover networks from previous runs
if [ "$DISABLE_CLEANUP" = false ]; then
    echo "🧹 Performing proactive cleanup of leftover networks..."
    leftover_networks=$(docker network ls --format "{{.Name}}" | grep -E "(^ctfnet|^tmp_ctfnet)" | wc -l)
    if [ "$leftover_networks" -gt 0 ]; then
        echo "⚠️  Found $leftover_networks leftover CTF networks from previous runs"
        echo "Cleaning them up to prevent subnet exhaustion..."
        
        # Use the same comprehensive cleanup logic
        docker network ls --format "{{.Name}}" | grep -E "(^ctfnet|^tmp_ctfnet)" | while read -r network_name; do
            if [ -n "$network_name" ]; then
                echo "Removing leftover network: $network_name"
                # First disconnect any containers
                docker network inspect "$network_name" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | \
                while read -r container_name; do
                    if [ -n "$container_name" ] && [ "$container_name" != "<no value>" ]; then
                        echo "  Disconnecting container $container_name from $network_name"
                        docker network disconnect "$network_name" "$container_name" -f 2>/dev/null || true
                    fi
                done
                # Remove the network
                docker network rm "$network_name" 2>/dev/null || true
            fi
        done
        
        echo "✅ Proactive cleanup completed"
    else
        echo "✅ No leftover CTF networks found - starting clean"
    fi

    # Check Docker subnet availability
    total_networks=$(docker network ls | grep bridge | wc -l)
    if [ "$total_networks" -gt 20 ]; then
        echo "⚠️  Warning: Found $total_networks bridge networks, approaching Docker subnet limits"
        echo "Consider running a full cleanup if you encounter network creation errors"
        echo "ℹ️  Note: The system now automatically waits for subnet space (up to 15 minutes) instead of failing immediately"
    fi
else
    echo "🚫 Cleanup disabled - skipping proactive cleanup of leftover networks"
fi

# Determine which challenges to run
if [ -z "$START_INDEX" ]; then
    # No specific index provided, run all challenges
    echo "No specific index provided. Running all challenges $TRY_TIMES time(s) each with $PARALLEL_TASKS parallel task(s)."
    # Get all challenge IDs and their paths from the JSON file using pipe delimiter
    challenges=$(jq -r 'to_entries[] | .key + "|" + .value.path' "$DATASET_JSON")
elif [ -z "$END_INDEX" ]; then
    # Only start index provided - run a single challenge
    # Check if the index is a number
    if ! [[ "$START_INDEX" =~ ^[0-9]+$ ]]; then
        echo "Error: Index must be a number"
        echo "Usage: $0 <dataset_name> [start_index] [end_index] [try_times] [parallel_tasks] [disable_cleanup]"
        exit 1
    fi

    # Get all challenges first using pipe delimiter
    all_challenges=$(jq -r 'to_entries[] | .key + "|" + .value.path' "$DATASET_JSON")
    
    # Count the total number of challenges
    total_challenges=$(echo "$all_challenges" | wc -l)
    
    if [ "$START_INDEX" -lt 1 ] || [ "$START_INDEX" -gt "$total_challenges" ]; then
        echo "Error: Index out of range. Valid range is 1-$total_challenges"
        exit 1
    fi
    
    # Get the challenge at the specified index (using sed to extract the line)
    challenges=$(echo "$all_challenges" | sed -n "${START_INDEX}p")
    
    # Get the challenge ID for display
    challenge_id=$(echo "$challenges" | cut -d'|' -f1)
    echo "Running challenge at index $START_INDEX: $challenge_id ($TRY_TIMES time(s)) with $PARALLEL_TASKS parallel task(s)"
else
    # Both start and end indexes provided - run a range of challenges
    # Check if both indexes are numbers
    if ! [[ "$START_INDEX" =~ ^[0-9]+$ ]] || ! [[ "$END_INDEX" =~ ^[0-9]+$ ]]; then
        echo "Error: Indexes must be numbers"
        echo "Usage: $0 <dataset_name> [start_index] [end_index] [try_times] [parallel_tasks] [disable_cleanup]"
        exit 1
    fi

    # Get all challenges first using pipe delimiter
    all_challenges=$(jq -r 'to_entries[] | .key + "|" + .value.path' "$DATASET_JSON")
    
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

# Process challenges sequentially by try number
# For each try number, run all challenges in parallel, then wait for completion before moving to next try
total_challenge_count=$(echo "$challenges" | wc -l)
task_count=$((total_challenge_count * TRY_TIMES))

echo "📊 Total tasks to run: $task_count ($total_challenge_count challenges × $TRY_TIMES tries each)"
echo "🔄 Running challenges sequentially by try number (all challenges try_1, then all challenges try_2, etc.)"
echo ""

# Loop through each try number sequentially
for try_num in $(seq 1 $TRY_TIMES); do
    echo ""
    echo "🔁 Starting Try $try_num of $TRY_TIMES"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Process all challenges for this try number in parallel
    instance_id=0
    try_start_time=$(date +%s)
    
    while IFS='|' read -r challenge_id challenge_path; do
        if [ -z "$challenge_path" ]; then
            continue
        fi
        
        # Wait for a slot to become available
        wait_for_slot
        
        # Increment counters
        ((total_jobs++))
        ((instance_id++))
        
        # Run challenge in tmux session
        run_challenge "$challenge_id" "$challenge_path" "$try_num" "$instance_id"
        
        # Shorter delay for try-based sequential execution
        delay_time=2
        echo "⏱️  Started challenge $challenge_id (try $try_num), waiting ${delay_time}s before next challenge..."
        sleep $delay_time
        
        # Show active sessions every 5 tasks within a try
        if [ $((instance_id % 5)) -eq 0 ]; then
            echo "📊 Try $try_num progress: Started $instance_id/$total_challenge_count challenges"
        fi
    done <<< "$challenges"
    
    echo "📋 All challenges for try $try_num have been started in tmux sessions"
    
    # Wait for all challenges in this try to complete before moving to next try
    echo "⏳ Waiting for all challenges in try $try_num to complete..."
    monitor_start_time=$(date +%s)
    
    while true; do
        # Clean up finished sessions first
        cleanup_finished_sessions
        
        # CRITICAL FIX: Run orphaned resource cleanup periodically during monitoring
        # Check every 30 seconds during the monitoring phase
        current_time=$(date +%s)
        if [ $((current_time % 30)) -eq 0 ]; then
            cleanup_orphaned_resources
        fi
        
        # Count active sessions
        active_count=$(get_active_session_count)
        
        if [ $active_count -eq 0 ]; then
            try_end_time=$(date +%s)
            try_execution_time=$((try_end_time - try_start_time))
            echo "✅ Try $try_num completed in ${try_execution_time}s!"
            
            # CRITICAL FIX: Final cleanup after each try completion
            echo "🧹 Performing final cleanup after try $try_num completion..."
            cleanup_orphaned_resources
            
            break
        fi
        
        # Show progress every 15 seconds for try-based execution
        elapsed=$((current_time - monitor_start_time))
        
        if [ $((elapsed % 15)) -eq 0 ] || [ $elapsed -lt 15 ]; then
            echo "📈 Try $try_num still running: $active_count tmux sessions active (${elapsed}s elapsed)"
        fi
        
        sleep 5
    done
    
    # Show summary for this try - only count files from this execution
    echo "🏁 Try $try_num summary:"
    successful_in_try=0
    failed_in_try=0
    
    for status_file in "${STATUS_FILE_PREFIX}"*_try${try_num}.txt; do
        if [ -f "$status_file" ]; then
            status=$(cat "$status_file" 2>/dev/null)
            case "$status" in
                "COMPLETED_SUCCESS"|"FINISHED")
                    ((successful_in_try++))
                    ;;
                "COMPLETED_FAILED")
                    ((failed_in_try++))
                    ;;
            esac
        fi
    done
    
    echo "  Successful: $successful_in_try"
    echo "  Failed: $failed_in_try"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
done

echo ""
echo "🏁 All tries completed!"

# CRITICAL FIX: Comprehensive final cleanup of ALL resources from this execution
echo ""
echo "🧹 Performing comprehensive final cleanup..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Final cleanup of any remaining sessions
cleanup_finished_sessions

# Final cleanup of orphaned resources 
cleanup_orphaned_resources

# Extra aggressive cleanup for this specific execution
echo "🔥 Extra aggressive cleanup for execution: $EXECUTION_ID"

# Stop and remove ALL containers from this execution
echo "  🐳 Stopping and removing ALL containers from this execution..."
docker stop $(docker ps -q --filter "name=${EXECUTION_ID}-parallel-") 2>/dev/null || echo "    No containers to stop"
docker rm $(docker ps -aq --filter "name=${EXECUTION_ID}-parallel-") 2>/dev/null || echo "    No containers to remove"

# Remove ALL networks from this execution
echo "  🌐 Removing ALL networks from this execution..."
execution_networks=$(docker network ls --format "{{.Name}}" | grep -E "(${EXECUTION_ID}|$(echo ${EXECUTION_ID} | cut -d'_' -f2))" || true)
if [ -n "$execution_networks" ]; then
    echo "$execution_networks" | while read -r network_name; do
        if [ -n "$network_name" ]; then
            echo "    Force removing network: $network_name"
            # Force disconnect all containers first
            docker network inspect "$network_name" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | \
            while read -r container_name; do
                if [ -n "$container_name" ] && [ "$container_name" != "<no value>" ]; then
                    docker network disconnect "$network_name" "$container_name" -f 2>/dev/null || true
                fi
            done
            sleep 1
            docker network rm "$network_name" 2>/dev/null || true
        fi
    done
fi

echo "✅ Comprehensive final cleanup completed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Count results from status files - only count files from this execution
successful_jobs=0
failed_jobs=0
completed_jobs=0

for status_file in "${STATUS_FILE_PREFIX}"*.txt; do
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