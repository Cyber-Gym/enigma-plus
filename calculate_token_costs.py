#!/usr/bin/env python3
import json
import os
import argparse
from pathlib import Path
import glob

def get_model_pricing(model_name):
    """Return input and output pricing per 1M tokens for the given model"""
    pricing = {
        # Anthropic models
        'bedrock-us.anthropic.claude-3-7-sonnet-20250219-v1-0': (3.0, 15.0),
        'bedrock-us.anthropic.claude-3-5-sonnet-20241022-v2-0': (3.0, 15.0),
        'google/gemini-2.5-pro': (1.25, 10),
        # Qwen models
        'qwen3-8b': (0.035, 0.138),
        'qwen3-agent-8b-0713': (0.035, 0.138),
        'qwen3-14b': (0.06, 0.24),
        'qwen3-agent-14b-0713': (0.06, 0.24),
        'qwen3-32b': (0.10, 0.30),
        'qwen3-agent-32b-0712': (0.10, 0.30),
        'deepseek-v3-0324': (0.28, 0.88),    # Placeholder pricing
        'swe-agent-7b-0715': (0.035, 0.138),
        'swe-agent-32b-0715': (0.10, 0.30),
    }
    
    return pricing.get(model_name, None)

def calculate_cost(tokens_sent, tokens_received, input_price, output_price):
    """Calculate cost based on tokens and pricing (per 1M tokens)"""
    input_cost = (tokens_sent / 1_000_000) * input_price
    output_cost = (tokens_received / 1_000_000) * output_price
    return input_cost + output_cost

def process_trajectory_file(traj_path):
    """Extract model stats from trajectory file"""
    try:
        with open(traj_path, 'r') as f:
            traj_data = json.load(f)
        
        # Look for model_stats in the info section
        if 'info' in traj_data and 'model_stats' in traj_data['info']:
            stats = traj_data['info']['model_stats']
            return stats.get('tokens_sent', 0), stats.get('tokens_received', 0)
        
        return 0, 0
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Could not process {traj_path}: {e}")
        return 0, 0

def find_model_directory(base_path, benchmark, model_name, pattern_suffix="__challenge__default_ctf__t-0.00__p-0.95__k-20__c-3.00__install-1"):
    """Find model directory, trying different patterns if the default doesn't exist"""
    model_dir = base_path / benchmark / 'try1' / f"{model_name}{pattern_suffix}"
    
    if model_dir.exists():
        return model_dir
    
    # Try to find directories that start with the model name
    search_pattern = str(base_path / benchmark / 'try1' / f"{model_name}__*")
    matching_dirs = glob.glob(search_pattern)
    
    if matching_dirs:
        # Return the first match
        return Path(matching_dirs[0])
    
    return None

def main():
    parser = argparse.ArgumentParser(description='Calculate token costs for CTF model runs')
    parser.add_argument('model_name', nargs='?', help='Model name (e.g., qwen3-8b)')
    parser.add_argument('--flag-only', action='store_true', 
                       help='Only consider tasks that captured a flag (model_patch is not null)')
    parser.add_argument('--list-models', action='store_true',
                       help='List available models and their pricing')
    
    args = parser.parse_args()
    
    if args.list_models:
        print("Available models and pricing ($/1M tokens):")
        print("-" * 60)
        pricing = {
            'bedrock-us.anthropic.claude-3-7-sonnet-20250219-v1-0': (3.0, 15.0),
            'bedrock-us.anthropic.claude-3-5-sonnet-20241022-v2-0': (3.0, 15.0),
            'qwen3-8b': (0.035, 0.138),
            'qwen3-14b': (0.06, 0.24),
            'qwen3-32b': (0.10, 0.30),
        }
        for model, (input_price, output_price) in pricing.items():
            print(f"{model:<50} Input: ${input_price:6.3f}  Output: ${output_price:6.3f}")
        return 0
    
    if not args.model_name:
        parser.error("model_name is required unless using --list-models")
    
    # Get pricing for the model
    pricing_info = get_model_pricing(args.model_name)
    if pricing_info is None:
        print(f"Warning: No pricing information for model '{args.model_name}'")
        print("Using default pricing: $0.05/1M input tokens, $0.20/1M output tokens")
        input_price, output_price = 0.05, 0.20
    else:
        input_price, output_price = pricing_info
    
    print(f"Model: {args.model_name}")
    print(f"Pricing: ${input_price}/1M input tokens, ${output_price}/1M output tokens")
    if args.flag_only:
        print("Mode: Only tasks with flags captured")
    print("-" * 60)
    
    benchmarks = ['intercode_ctf', 'cybench', 'nyu_ctf']
    # Benchmark totals for success rate calculation
    benchmark_totals = {
        'intercode_ctf': 91,
        'cybench': 40, 
        'nyu_ctf': 192
    }
    base_path = Path('/mnt/people/zhuoterq/SWE-agent/trajectories')
    
    total_cost = 0.0
    total_tokens_sent = 0
    total_tokens_received = 0
    total_tasks = 0
    flag_tasks = 0
    
    # Track successful tasks separately
    flag_cost = 0.0
    flag_tokens_sent = 0
    flag_tokens_received = 0
    
    # Track total possible tasks across all benchmarks
    total_possible_tasks = 0
    
    for benchmark in benchmarks:
        print(f"\nProcessing {benchmark}...")
        
        # Add to total possible tasks
        total_possible_tasks += benchmark_totals[benchmark]
        
        # Find model directory (try different patterns)
        model_dir = find_model_directory(base_path, benchmark, args.model_name)
        
        if model_dir is None:
            print(f"  Directory not found for model {args.model_name}")
            continue
        
        print(f"  Found directory: {model_dir.name}")
        
        # Read all_preds.jsonl
        all_preds_path = model_dir / 'all_preds.jsonl'
        if not all_preds_path.exists():
            print(f"  all_preds.jsonl not found: {all_preds_path}")
            continue
        
        benchmark_cost = 0.0
        benchmark_tokens_sent = 0
        benchmark_tokens_received = 0
        benchmark_tasks = 0
        benchmark_flag_tasks = 0
        
        # First pass: collect all entries for each instance_id
        instance_entries = {}
        
        with open(all_preds_path, 'r') as f:
            for line in f:
                try:
                    pred_data = json.loads(line.strip())
                    instance_id = pred_data.get('instance_id')
                    model_patch = pred_data.get('model_patch')
                    
                    if not instance_id:
                        continue
                    
                    # Store entry for this instance_id
                    if instance_id not in instance_entries:
                        instance_entries[instance_id] = []
                    instance_entries[instance_id].append({
                        'instance_id': instance_id,
                        'model_patch': model_patch,
                        'has_flag': model_patch is not None
                    })
                
                except json.JSONDecodeError as e:
                    print(f"    Warning: Could not parse line in all_preds.jsonl: {e}")
                    continue
        
        # Second pass: select the best entry for each instance_id
        selected_entries = {}
        for instance_id, entries in instance_entries.items():
            # Prioritize entries with flags, otherwise use the first one
            flagged_entries = [e for e in entries if e['has_flag']]
            if flagged_entries:
                selected_entries[instance_id] = flagged_entries[0]  # Use first flagged entry
            else:
                selected_entries[instance_id] = entries[0]  # Use first entry if no flags
        
        # Third pass: process the selected entries
        for instance_id, entry in selected_entries.items():
            model_patch = entry['model_patch']
            has_flag = entry['has_flag']
            
            # Check if we should skip this task (flag-only mode)
            if args.flag_only and not has_flag:
                continue
            
            # Find corresponding trajectory file
            traj_path = model_dir / f"{instance_id}.traj"
            if not traj_path.exists():
                print(f"    Warning: Trajectory file not found: {traj_path}")
                continue
            
            # Process trajectory file
            tokens_sent, tokens_received = process_trajectory_file(traj_path)
            
            if tokens_sent > 0 or tokens_received > 0:
                cost = calculate_cost(tokens_sent, tokens_received, input_price, output_price)
                
                benchmark_cost += cost
                benchmark_tokens_sent += tokens_sent
                benchmark_tokens_received += tokens_received
                benchmark_tasks += 1
                
                if has_flag:
                    benchmark_flag_tasks += 1
                    # Track successful tasks separately
                    if not args.flag_only:  # Only track separately when not in flag-only mode
                        flag_cost += cost
                        flag_tokens_sent += tokens_sent
                        flag_tokens_received += tokens_received
        
        print(f"  Tasks processed: {benchmark_tasks}")
        print(f"  Tasks with flags: {benchmark_flag_tasks}")
        print(f"  Tokens sent: {benchmark_tokens_sent:,}")
        print(f"  Tokens received: {benchmark_tokens_received:,}")
        print(f"  Cost: ${benchmark_cost:.4f}")
        print(f"  Success rate for {benchmark}: {benchmark_flag_tasks}/{benchmark_totals[benchmark]} ({(benchmark_flag_tasks/benchmark_totals[benchmark]*100):.1f}%)")
        
        total_cost += benchmark_cost
        total_tokens_sent += benchmark_tokens_sent
        total_tokens_received += benchmark_tokens_received
        total_tasks += benchmark_tasks
        flag_tasks += benchmark_flag_tasks
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total tasks processed: {total_tasks}")
    print(f"Total tasks with flags: {flag_tasks}")
    print(f"Total tokens sent: {total_tokens_sent:,}")
    print(f"Total tokens received: {total_tokens_received:,}")
    print(f"Total cost: ${total_cost:.4f}")
    
    if total_tasks > 0:
        print(f"Average cost per task: ${total_cost/total_tasks:.4f}")
    if flag_tasks > 0:
        # Use correct benchmark totals for overall success rate
        overall_success_rate = (flag_tasks / total_possible_tasks) * 100
        print(f"Overall success rate: {flag_tasks}/{total_possible_tasks} ({overall_success_rate:.1f}%)")
        
        if args.flag_only:
            print(f"Average cost per successful task: ${total_cost/flag_tasks:.4f}")
        else:
            # Show successful tasks breakdown when not in flag-only mode
            print()
            print("SUCCESSFUL TASKS ONLY:")
            print("-" * 40)
            print(f"Successful tasks: {flag_tasks}")
            print(f"Tokens sent (successful): {flag_tokens_sent:,}")
            print(f"Tokens received (successful): {flag_tokens_received:,}")
            print(f"Cost (successful): ${flag_cost:.4f}")
            if flag_tasks > 0:
                print(f"Average cost per successful task: ${flag_cost/flag_tasks:.4f}")

if __name__ == '__main__':
    main() 