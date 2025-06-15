#!/bin/bash
export OPENAI_API_KEY=sk-30203ed9ad15499a9a6e09ea29383a2f
export OPENAI_API_BASE_URL=http://localhost:30000/v1

DATASET_JSON="../NYU_CTF_Bench/test_dataset.json"
MODEL_NAME="deepseek-r1-0528"
IMAGE_NAME="sweagent/enigma:latest"
CONFIG_FILE="config/default_ctf.yaml"
HOST_URL="http://localhost:8000"
PER_INSTANCE_STEP_LIMIT=40

# export SWE_AGENT_ACTION_TIMEOUT=60
# Check if indexes were provided
START_INDEX=$1
END_INDEX=$2
TRY_TIMES=$3

# Set default try times to 1 if not provided
if [ -z "$TRY_TIMES" ]; then
    TRY_TIMES=1
else
    # Validate that TRY_TIMES is a positive number
    if ! [[ "$TRY_TIMES" =~ ^[0-9]+$ ]] || [ "$TRY_TIMES" -lt 1 ]; then
        echo "Error: Try times must be a positive number"
        echo "Usage: $0 [start_index] [end_index] [try_times]"
        exit 1
    fi
fi

if [ -z "$START_INDEX" ]; then
    # No specific index provided, run all challenges
    echo "No specific index provided. Running all challenges $TRY_TIMES time(s) each."
    # Get all challenge IDs and their paths from the JSON file
    challenges=$(jq -r 'to_entries[] | [.key, .value.path] | @tsv' "$DATASET_JSON")
elif [ -z "$END_INDEX" ]; then
    # Only start index provided - run a single challenge
    # Check if the index is a number
    if ! [[ "$START_INDEX" =~ ^[0-9]+$ ]]; then
        echo "Error: Index must be a number"
        echo "Usage: $0 [start_index] [end_index] [try_times]"
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
    echo "Running challenge at index $START_INDEX: $challenge_id ($TRY_TIMES time(s))"
else
    # Both start and end indexes provided - run a range of challenges
    # Check if both indexes are numbers
    if ! [[ "$START_INDEX" =~ ^[0-9]+$ ]] || ! [[ "$END_INDEX" =~ ^[0-9]+$ ]]; then
        echo "Error: Indexes must be numbers"
        echo "Usage: $0 [start_index] [end_index] [try_times]"
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
    
    echo "Running challenges from index $START_INDEX to $END_INDEX ($TRY_TIMES time(s) each)"
fi

# Run each challenge directly
while IFS=$'\t' read -r challenge_id challenge_path; do
    if [ -z "$challenge_path" ]; then
        continue
    fi
    
    DATA_PATH="../NYU_CTF_Bench/${challenge_path}/challenge.json"
    REPO_PATH="../NYU_CTF_Bench/${challenge_path}/"
    
    echo "Starting challenge: $challenge_id ($challenge_path)"
    
    # Check if the data and repo paths exist
    if [ ! -f "$DATA_PATH" ]; then
        echo "Error: Data file not found at $DATA_PATH"
        continue
    fi
    if [ ! -d "$REPO_PATH" ]; then
        echo "Error: Repo directory not found at $REPO_PATH"
        continue
    fi
    
    # Run the challenge multiple times based on TRY_TIMES
    for try_num in $(seq 1 $TRY_TIMES); do
        if [ "$TRY_TIMES" -gt 1 ]; then
            echo "Running challenge: $challenge_id (attempt $try_num/$TRY_TIMES)"
        else
            echo "Running challenge: $challenge_id"
        fi
        
        python run.py \
            --model_name "$MODEL_NAME" \
            --ctf \
            --image_name "$IMAGE_NAME" \
            --data_path "$DATA_PATH" \
            --repo_path "$REPO_PATH" \
            --config_file "$CONFIG_FILE" \
            --host_url "$HOST_URL" \
            --per_instance_step_limit $PER_INSTANCE_STEP_LIMIT \
            --temperature=0.6 \
            --top_p=0.95 \
            --top_k=0
        
        if [ "$TRY_TIMES" -gt 1 ]; then
            echo "Finished challenge: $challenge_id (attempt $try_num/$TRY_TIMES)"
        else
            echo "Finished challenge: $challenge_id"
        fi
    done
    
    echo "Completed all attempts for challenge: $challenge_id"
done <<< "$challenges"

echo "All challenges completed."