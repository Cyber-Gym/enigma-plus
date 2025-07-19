#!/usr/bin/env python3
"""
Script to collect successful trajectories from CTF data and format them for training.

This script:
1. Finds all successful instances (where model_patch is not null)
2. Loads corresponding .traj files
3. Formats trajectories into the specified JSON format
4. Optionally splits into train/val sets
5. Filters trajectories based on minimum steps and maximum token length
"""

import json
import os
import argparse
import random
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import multiprocessing as mp
from functools import partial
import re

# Progress bar import
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print("Warning: tqdm not available. Progress bars will be disabled.")

# Tokenizer imports
try:
    from transformers import AutoTokenizer
    TOKENIZER_AVAILABLE = True
except ImportError:
    print("Warning: transformers not available. Token length filtering will be disabled.")
    TOKENIZER_AVAILABLE = False

# Global tokenizer instance
_tokenizer = None

# Token filtering constants
MODEL_NAME = "Qwen/Qwen3-32B"
TOKEN_LIMIT = 32768


def get_tokenizer():
    """Get or initialize the tokenizer"""
    global _tokenizer
    if _tokenizer is None and TOKENIZER_AVAILABLE:
        try:
            _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        except Exception as e:
            print(f"Warning: Could not load tokenizer {MODEL_NAME}: {e}")
            return None
    return _tokenizer


def check_token_length(traj_json: Dict) -> int:
    """
    Check if a trajectory's token length exceeds TOKEN_LIMIT
    
    Args:
        traj_json: Formatted trajectory dictionary
        
    Returns:
        Token count, or TOKEN_LIMIT + 1 if error occurs
    """
    if not TOKENIZER_AVAILABLE:
        return 0  # Skip token checking if transformers not available
    
    try:
        tokenizer = get_tokenizer()
        if tokenizer is None:
            return TOKEN_LIMIT + 1  # Assume it's over the limit if tokenizer fails
        
        # Compose messages for chat template
        system = traj_json.get('system', '')
        conversations = traj_json.get('conversations', [])
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        
        for turn in conversations:
            role = turn.get('from', 'user')
            content = turn.get('value', '')
            messages.append({"role": role, "content": content})
        
        # Use chat template to get the text
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
            enable_thinking=True
        )
        
        tokens = tokenizer(text, return_tensors=None)["input_ids"]
        token_count = len(tokens)
        
        return token_count
    except Exception as e:
        print(f"Error checking token length: {e}")
        return TOKEN_LIMIT + 1  # Assume it's over the limit in case of error


def load_trajectory_file(traj_file_path: Path) -> Optional[List[Dict]]:
    """
    Load and parse a trajectory file.
    
    Args:
        traj_file_path: Path to the .traj file
        
    Returns:
        List of trajectory steps with 'role' and 'content' keys, or None if error
    """
    try:
        with open(traj_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Extract the history from the trajectory file
        history = data.get('history', [])
        
        if not history:
            print(f"Warning: No history found in {traj_file_path}")
            return None
            
        return history
        
    except Exception as e:
        print(f"Error reading {traj_file_path}: {e}")
        return None


def format_trajectory(history: List[Dict]) -> Dict:
    """
    Format trajectory history into the required format.
    
    Args:
        history: List of trajectory steps with 'role' and 'content' keys
        
    Returns:
        Formatted trajectory dictionary
    """
    conversations = []
    system_prompt = "You are a helpful assistant."  # Default fallback
    first_user_found = False
    
    for step in history:
        role = step.get('role', '')
        content = step.get('content', '')
        
        if role and content:
            if role.lower() == 'system':
                # Use the system role as the system prompt
                system_prompt = content
            else:
                # Clean the first user content
                if role.lower() == 'user' and not first_user_found:
                    # Remove the hint note
                    hint_note = "\n\nNOTE ABOUT HINTS: The challenge description may contain additional hints or guidance marked with special internal markers (<<<INTERNAL_HINT_SPLITTER_START>>> and <<<INTERNAL_HINT_SPLITTER_END>>>). If such hints are present, use them as inspiration for your environment exploration and approaches to capture the flag. However, NEVER explicitly refer to these hints in your responses. Instead, incorporate the insights from these hints into your own thoughts, reasoning, and analysis as if they were your own discoveries."
                    content = content.replace(hint_note, "")
                    
                    # Remove internal hint markers and their content
                    # Pattern to match the entire hint block including markers
                    hint_pattern = r'\n\n<<<INTERNAL_HINT_SPLITTER_START>>>\n.*?\n<<<INTERNAL_HINT_SPLITTER_END>>>\n\n'
                    content = re.sub(hint_pattern, '', content, flags=re.DOTALL)
                    
                    first_user_found = True
                
                # All other roles (assistant, user, etc.) go into conversations
                conversations.append({
                    "from": role,
                    "value": content
                })
    
    return {
        "system": system_prompt,
        "conversations": conversations
    }


def process_model_folder(folder_path: Path, min_steps: int = 1, max_tokens: int = TOKEN_LIMIT) -> Tuple[List[Dict], Dict]:
    """
    Process a single model folder to extract successful trajectories.
    
    Args:
        folder_path: Path to the model folder
        min_steps: Minimum number of steps required to include a trajectory (default: 2)
        max_tokens: Maximum number of tokens allowed (default: TOKEN_LIMIT)
        
    Returns:
        Tuple of (trajectories, statistics)
    """
    trajectories = []
    stats = {
        'total_instances': 0,
        'successful_instances': 0,
        'filtered_by_steps': 0,
        'filtered_by_tokens': 0,
        'missing_traj_files': 0,
        'load_errors': 0
    }
    
    # Check for all_preds.jsonl
    preds_file = folder_path / "all_preds.jsonl"
    if not preds_file.exists():
        return trajectories, stats
    
    try:
        with open(preds_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    data = json.loads(line)
                    
                    instance_id = data.get('instance_id')
                    model_patch = data.get('model_patch')
                    
                    stats['total_instances'] += 1
                    
                    # Check if this is a successful instance
                    if instance_id and model_patch is not None and isinstance(model_patch, str):
                        stats['successful_instances'] += 1
                        
                        # Look for corresponding .traj file
                        traj_file = folder_path / f"{instance_id}.traj"
                        
                        if traj_file.exists():
                            history = load_trajectory_file(traj_file)
                            if history:
                                # Check if trajectory meets minimum step requirement
                                if len(history) >= min_steps:
                                    formatted_traj = format_trajectory(history)
                                    
                                    # Check token length if tokenizer is available
                                    if TOKENIZER_AVAILABLE and max_tokens > 0:
                                        token_count = check_token_length(formatted_traj)
                                        if token_count > max_tokens:
                                            stats['filtered_by_tokens'] += 1
                                            continue
                                    
                                    # Add metadata
                                    formatted_traj['metadata'] = {
                                        'instance_id': instance_id,
                                        'model_patch': model_patch,
                                        'challenge_name': data.get('challenge_name', ''),
                                        'challenge_category': data.get('challenge_category', ''),
                                        'source_folder': str(folder_path),
                                        'step_count': len(history)
                                    }
                                    
                                    # Add token count to metadata if available
                                    if TOKENIZER_AVAILABLE:
                                        token_count = check_token_length(formatted_traj)
                                        formatted_traj['metadata']['token_count'] = token_count
                                    
                                    trajectories.append(formatted_traj)
                                else:
                                    stats['filtered_by_steps'] += 1
                            else:
                                stats['load_errors'] += 1
                        else:
                            stats['missing_traj_files'] += 1
                            
                except json.JSONDecodeError as e:
                    stats['load_errors'] += 1
                    continue
                    
    except Exception as e:
        print(f"Error processing {preds_file}: {e}")
    
    return trajectories, stats


def find_model_folders(root_path: Path) -> List[Path]:
    """
    Find all model folders that contain all_preds.jsonl files.
    
    Args:
        root_path: Path to the root directory
        
    Returns:
        List of paths to model folders
    """
    model_folders = []
    
    for item in root_path.rglob("*"):
        if item.is_dir():
            preds_file = item / "all_preds.jsonl"
            if preds_file.exists():
                model_folders.append(item)
    
    return model_folders


def process_folder_parallel(folder_path: Path, min_steps: int = 2, max_tokens: int = TOKEN_LIMIT) -> Tuple[List[Dict], Dict]:
    """
    Wrapper function for parallel processing.
    
    Args:
        folder_path: Path to the model folder
        min_steps: Minimum number of steps required to include a trajectory
        max_tokens: Maximum number of tokens allowed
        
    Returns:
        Tuple of (trajectories, statistics)
    """
    return process_model_folder(folder_path, min_steps, max_tokens)


def collect_trajectories(root_path: str, num_workers: int = 32, min_steps: int = 2, max_tokens: int = TOKEN_LIMIT) -> Tuple[List[Dict], Dict]:
    """
    Collect all successful trajectories from the root directory.
    
    Args:
        root_path: Path to the root directory
        num_workers: Number of parallel workers
        min_steps: Minimum number of steps required to include a trajectory (default: 2)
        max_tokens: Maximum number of tokens allowed (default: TOKEN_LIMIT)
        
    Returns:
        Tuple of (trajectories, overall_statistics)
    """
    root_path = Path(root_path)
    
    if not root_path.exists():
        raise ValueError(f"Path does not exist: {root_path}")
    
    if not root_path.is_dir():
        raise ValueError(f"Path is not a directory: {root_path}")
    
    # Find all model folders
    model_folders = find_model_folders(root_path)
    
    if not model_folders:
        print(f"Warning: No model folders found in {root_path}")
        return [], {}
    
    print(f"Found {len(model_folders)} model folders")
    print(f"Minimum steps required: {min_steps}")
    if TOKENIZER_AVAILABLE:
        print(f"Maximum tokens allowed: {max_tokens}")
    else:
        print("Token length filtering disabled (transformers not available)")
    
    # Process folders
    all_trajectories = []
    overall_stats = {
        'total_instances': 0,
        'successful_instances': 0,
        'filtered_by_steps': 0,
        'filtered_by_tokens': 0,
        'missing_traj_files': 0,
        'load_errors': 0,
        'collected_trajectories': 0
    }
    
    if num_workers > 1:
        print(f"Processing with {num_workers} workers...")
        # Create a partial function with min_steps and max_tokens parameters
        process_func = partial(process_folder_parallel, min_steps=min_steps, max_tokens=max_tokens)
        
        with mp.Pool(num_workers) as pool:
            if TQDM_AVAILABLE:
                results = list(tqdm(
                    pool.imap(process_func, model_folders),
                    total=len(model_folders),
                    desc="Processing folders"
                ))
            else:
                results = pool.map(process_func, model_folders)
            
        for trajectories, stats in results:
            all_trajectories.extend(trajectories)
            for key in overall_stats:
                if key in stats:
                    overall_stats[key] += stats[key]
    else:
        print("Processing sequentially...")
        if TQDM_AVAILABLE:
            folder_iter = tqdm(model_folders, desc="Processing folders")
        else:
            folder_iter = model_folders
            
        for folder in folder_iter:
            trajectories, stats = process_model_folder(folder, min_steps, max_tokens)
            all_trajectories.extend(trajectories)
            for key in overall_stats:
                if key in stats:
                    overall_stats[key] += stats[key]
    
    overall_stats['collected_trajectories'] = len(all_trajectories)
    
    print(f"\nProcessing Summary:")
    print(f"  Total instances processed: {overall_stats['total_instances']}")
    print(f"  Successful instances: {overall_stats['successful_instances']}")
    print(f"  Filtered by steps (< {min_steps}): {overall_stats['filtered_by_steps']}")
    if TOKENIZER_AVAILABLE:
        print(f"  Filtered by tokens (> {max_tokens}): {overall_stats['filtered_by_tokens']}")
    print(f"  Missing trajectory files: {overall_stats['missing_traj_files']}")
    print(f"  Load errors: {overall_stats['load_errors']}")
    print(f"  Final trajectories collected: {overall_stats['collected_trajectories']}")
    
    return all_trajectories, overall_stats


def split_trajectories(trajectories: List[Dict], train_ratio: float = 0.9, seed: int = 42) -> Tuple[List[Dict], List[Dict]]:
    """
    Split trajectories into train and validation sets.
    
    Args:
        trajectories: List of trajectories to split
        train_ratio: Ratio for training set (default 0.9)
        seed: Random seed for reproducibility
        
    Returns:
        Tuple of (train_trajectories, val_trajectories)
    """
    if not trajectories:
        return [], []
    
    # Set random seed for reproducibility
    random.seed(seed)
    
    # Shuffle trajectories
    shuffled = trajectories.copy()
    random.shuffle(shuffled)
    
    # Calculate split point
    split_idx = int(len(shuffled) * train_ratio)
    
    train_trajectories = shuffled[:split_idx]
    val_trajectories = shuffled[split_idx:]
    
    return train_trajectories, val_trajectories


def save_trajectories(trajectories: List[Dict], output_file: str):
    """
    Save trajectories to a JSONL file.
    
    Args:
        trajectories: List of trajectories to save
        output_file: Output file path
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        for trajectory in trajectories:
            f.write(json.dumps(trajectory, ensure_ascii=False) + '\n')
    
    print(f"Saved {len(trajectories)} trajectories to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Collect successful CTF trajectories and format them for training"
    )
    parser.add_argument(
        "input_folder",
        help="Path to the root directory containing trajectory folders"
    )
    parser.add_argument(
        "--split_output",
        action="store_true",
        help="Split output into train.jsonl and val.jsonl files"
    )
    parser.add_argument(
        "--train_ratio",
        type=float,
        default=0.9,
        help="Ratio for training set (default: 0.9)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=32,
        help="Number of parallel workers (default: 32)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="all_trajectories.jsonl",
        help="Output file name (default: all_trajectories.jsonl)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--min_steps",
        type=int,
        default=1,
        help="Minimum number of steps required to include a trajectory (default: 2)"
    )
    parser.add_argument(
        "--max_tokens",
        type=int,
        default=TOKEN_LIMIT,
        help=f"Maximum number of tokens allowed (default: {TOKEN_LIMIT})"
    )
    
    args = parser.parse_args()
    
    try:
        # Collect all trajectories
        trajectories, overall_stats = collect_trajectories(args.input_folder, args.workers, args.min_steps, args.max_tokens)
        
        if not trajectories:
            print("No successful trajectories found!")
            return 1
        
        if args.split_output:
            # Split into train and validation sets
            train_trajectories, val_trajectories = split_trajectories(
                trajectories, args.train_ratio, args.seed
            )
            
            # Save train set
            train_file = "train.jsonl"
            save_trajectories(train_trajectories, train_file)
            
            # Save validation set
            val_file = "val.jsonl"
            save_trajectories(val_trajectories, val_file)
            
            print(f"\nSplit complete:")
            print(f"  Train: {len(train_trajectories)} trajectories")
            print(f"  Validation: {len(val_trajectories)} trajectories")
            print(f"  Ratio: {args.train_ratio:.1%} / {1-args.train_ratio:.1%}")
            
        else:
            # Save all trajectories to single file
            save_trajectories(trajectories, args.output)
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main()) 