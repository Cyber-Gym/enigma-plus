#!/usr/bin/env python3
"""
Script to analyze CTF trajectories and calculate flag capture statistics.

This script processes a folder containing various trajectory subfolders,
each with an all_preds.jsonl file containing prediction results.
It calculates:
1. Total number of instances with captured flags
2. Total number of unique instances
3. Total number of successful trajectories (individual model runs)
4. Success rate (captured flags / total instances)
5. Average step count of successful trajectories
6. Step distribution (min, median, max) for successful trajectories
"""

import json
import os
import argparse
import statistics
from pathlib import Path
from typing import Dict, Set, Tuple, List


def analyze_trajectory_folder(folder_path: str) -> Tuple[int, Set[str], Set[str], int, List[Tuple[str, int]]]:
    """
    Analyze a single trajectory folder to count captured flags and unique instances.
    
    Args:
        folder_path: Path to the trajectory folder
        
    Returns:
        Tuple of (captured_flags_count, unique_instance_ids, captured_instance_ids, total_successful_trajectories, step_data)
    """
    captured_instances = set()
    unique_instances = set()
    successful_trajectories = 0
    step_data = []  # List of (instance_id, step_count) tuples
    
    # Look for all_preds.jsonl file in the folder
    preds_file = Path(folder_path) / "all_preds.jsonl"
    
    if not preds_file.exists():
        print(f"Warning: No all_preds.jsonl found in {folder_path}")
        return 0, set(), set(), 0, []
    
    try:
        with open(preds_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    data = json.loads(line)
                    
                    # Extract instance_id and model_patch
                    instance_id = data.get('instance_id')
                    model_patch = data.get('model_patch')
                    
                    if instance_id:
                        unique_instances.add(instance_id)
                        
                        # Check if flag was captured (model_patch is not null and is a string)
                        if model_patch is not None and isinstance(model_patch, str):
                            captured_instances.add(instance_id)
                            successful_trajectories += 1
                            
                            # Load trajectory file to count steps
                            traj_file = Path(folder_path) / f"{instance_id}.traj"
                            if traj_file.exists():
                                try:
                                    with open(traj_file, 'r', encoding='utf-8') as traj_f:
                                        traj_data = json.load(traj_f)
                                        trajectory = traj_data.get('trajectory', [])
                                        step_count = len(trajectory)
                                        step_data.append((instance_id, step_count))
                                except Exception as e:
                                    print(f"Warning: Could not read trajectory file {traj_file}: {e}")
                                    # Add 0 steps for this trajectory if we can't read it
                                    step_data.append((instance_id, 0))
                            else:
                                print(f"Warning: No trajectory file found for successful instance {instance_id}")
                                # Add 0 steps for this trajectory if file doesn't exist
                                step_data.append((instance_id, 0))
                            
                except json.JSONDecodeError as e:
                    print(f"Warning: Invalid JSON on line {line_num} in {preds_file}: {e}")
                    continue
                    
    except Exception as e:
        print(f"Error reading {preds_file}: {e}")
        return 0, set(), set(), 0, []
    
    return len(captured_instances), unique_instances, captured_instances, successful_trajectories, step_data


def find_model_result_folders(root_path: Path) -> list:
    """
    Find all model result folders that contain all_preds.jsonl files.
    
    Args:
        root_path: Path to the root directory
        
    Returns:
        List of paths to model result folders
    """
    model_folders = []
    
    # Walk through all subdirectories recursively
    for item in root_path.rglob("*"):
        if item.is_dir():
            # Check if this directory contains all_preds.jsonl
            preds_file = item / "all_preds.jsonl"
            if preds_file.exists():
                model_folders.append(item)
    
    return model_folders


def analyze_trajectories_root(root_path: str) -> Dict:
    """
    Analyze all trajectory folders in the root directory.
    
    Args:
        root_path: Path to the root directory containing trajectory folders
        
    Returns:
        Dictionary with analysis results
    """
    root_path = Path(root_path)
    
    if not root_path.exists():
        raise ValueError(f"Path does not exist: {root_path}")
    
    if not root_path.is_dir():
        raise ValueError(f"Path is not a directory: {root_path}")
    
    all_unique_instances = set()
    all_captured_instances = set()
    total_successful_trajectories = 0
    all_step_counts = []
    all_step_data = []  # List of (instance_id, step_count, folder_path) tuples
    folder_results = {}
    
    # Find all model result folders that contain all_preds.jsonl
    model_folders = find_model_result_folders(root_path)
    
    if not model_folders:
        print(f"Warning: No model result folders with all_preds.jsonl found in {root_path}")
        return {
            'total_captured_flags': 0,
            'total_unique_instances': 0,
            'total_successful_trajectories': 0,
            'success_rate': 0.0,
            'folder_results': {},
            'all_unique_instances': set(),
            'all_captured_instances': set(),
            'step_statistics': {
                'average_steps': 0.0,
                'min_steps': 0,
                'median_steps': 0.0,
                'max_steps': 0,
                'total_step_counts': []
            },
            'top_5_shortest_trajectories': []
        }
    
    print(f"Found {len(model_folders)} model result folders with all_preds.jsonl")
    
    for folder in model_folders:
        # Create a descriptive folder name using the relative path
        relative_path = folder.relative_to(root_path)
        folder_name = str(relative_path).replace('/', '_')
        
        print(f"Analyzing {folder_name}...")
        
        captured_count, unique_instances, captured_instances, successful_trajectories, step_data = analyze_trajectory_folder(str(folder))
        
        # Calculate step statistics for this folder
        folder_step_stats = {}
        if step_data:
            step_counts = [s[1] for s in step_data]
            folder_step_stats = {
                'average_steps': statistics.mean(step_counts),
                'min_steps': min(step_counts),
                'median_steps': statistics.median(step_counts),
                'max_steps': max(step_counts),
                'total_step_counts': step_data
            }
            
            # Add folder path to step data for tracking
            for instance_id, step_count in step_data:
                all_step_data.append((instance_id, step_count, str(folder)))
        else:
            folder_step_stats = {
                'average_steps': 0.0,
                'min_steps': 0,
                'median_steps': 0.0,
                'max_steps': 0,
                'total_step_counts': []
            }
        
        folder_results[folder_name] = {
            'captured_flags': captured_count,
            'total_instances': len(unique_instances),
            'successful_trajectories': successful_trajectories,
            'success_rate': captured_count / len(unique_instances) if len(unique_instances) > 0 else 0.0,
            'unique_instances': unique_instances,
            'captured_instances': captured_instances,
            'full_path': str(folder),
            'step_statistics': folder_step_stats
        }
        
        all_unique_instances.update(unique_instances)
        all_captured_instances.update(captured_instances)
        total_successful_trajectories += successful_trajectories
        all_step_counts.extend([s[1] for s in step_data])
    
    total_unique_instances = len(all_unique_instances)
    total_captured_flags = len(all_captured_instances)
    overall_success_rate = total_captured_flags / total_unique_instances if total_unique_instances > 0 else 0.0
    
    # Calculate overall step statistics
    overall_step_stats = {}
    if all_step_counts:
        overall_step_stats = {
            'average_steps': statistics.mean(all_step_counts),
            'min_steps': min(all_step_counts),
            'median_steps': statistics.median(all_step_counts),
            'max_steps': max(all_step_counts),
            'total_step_counts': all_step_counts
        }
    else:
        overall_step_stats = {
            'average_steps': 0.0,
            'min_steps': 0,
            'median_steps': 0.0,
            'max_steps': 0,
            'total_step_counts': []
        }
    
    # Find top 5 shortest trajectories
    top_5_shortest = []
    if all_step_data:
        # Sort by step count (ascending) and take top 5
        sorted_trajectories = sorted(all_step_data, key=lambda x: x[1])
        top_5_shortest = sorted_trajectories[:5]
    
    return {
        'total_captured_flags': total_captured_flags,
        'total_unique_instances': total_unique_instances,
        'total_successful_trajectories': total_successful_trajectories,
        'success_rate': overall_success_rate,
        'folder_results': folder_results,
        'all_unique_instances': all_unique_instances,
        'all_captured_instances': all_captured_instances,
        'step_statistics': overall_step_stats,
        'top_5_shortest_trajectories': top_5_shortest
    }


def print_results(results: Dict):
    """Print the analysis results in a formatted way."""
    print("\n" + "="*60)
    print("CTF TRAJECTORY ANALYSIS RESULTS")
    print("="*60)
    
    print(f"\nOverall Statistics:")
    print(f"  Total unique instances with captured flags: {results['total_captured_flags']}")
    print(f"  Total unique instances: {results['total_unique_instances']}")
    print(f"  Total successful trajectories: {results['total_successful_trajectories']}")
    print(f"  Overall success rate: {results['success_rate']:.2%}")
    
    # Print step statistics
    step_stats = results['step_statistics']
    if step_stats['total_step_counts']:
        print(f"\nStep Statistics (Successful Trajectories):")
        print(f"  Average steps: {step_stats['average_steps']:.1f}")
        print(f"  Median steps: {step_stats['median_steps']:.1f}")
        print(f"  Min steps: {step_stats['min_steps']}")
        print(f"  Max steps: {step_stats['max_steps']}")
        print(f"  Total trajectories analyzed: {len(step_stats['total_step_counts'])}")
    else:
        print(f"\nStep Statistics: No successful trajectories found")
    
    # Print top 5 shortest trajectories
    top_5_shortest = results['top_5_shortest_trajectories']
    if top_5_shortest:
        print(f"\nTop 5 Shortest Successful Trajectories:")
        print("-" * 60)
        for i, (instance_id, step_count, folder_path) in enumerate(top_5_shortest, 1):
            # Extract a shorter display name from the folder path
            folder_name = Path(folder_path).name
            # Create the full path to the .traj file
            traj_file_path = Path(folder_path) / f"{instance_id}.traj"
            print(f"  {i}. Instance: {instance_id}")
            print(f"     Steps: {step_count}")
            print(f"     Folder: {folder_name}")
            print(f"     Full Path: {traj_file_path}")
            print()
    else:
        print(f"\nTop 5 Shortest Trajectories: No successful trajectories found")
    
    print(f"\nPer-Model Breakdown:")
    print("-" * 60)
    
    for folder_name, folder_data in results['folder_results'].items():
        print(f"{folder_name}:")
        print(f"  Captured flags: {folder_data['captured_flags']}")
        print(f"  Total instances: {folder_data['total_instances']}")
        print(f"  Successful trajectories: {folder_data['successful_trajectories']}")
        print(f"  Success rate: {folder_data['success_rate']:.2%}")
        
        # Print step statistics for this folder
        folder_step_stats = folder_data['step_statistics']
        if folder_step_stats['total_step_counts']:
            print(f"  Step statistics:")
            print(f"    Average: {folder_step_stats['average_steps']:.1f}")
            print(f"    Median: {folder_step_stats['median_steps']:.1f}")
            print(f"    Min: {folder_step_stats['min_steps']}")
            print(f"    Max: {folder_step_stats['max_steps']}")
        
        print(f"  Path: {folder_data['full_path']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze CTF trajectories and calculate flag capture statistics"
    )
    parser.add_argument(
        "path",
        help="Path to the root directory containing trajectory folders"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file to save results as JSON (optional)"
    )
    
    args = parser.parse_args()
    
    try:
        results = analyze_trajectories_root(args.path)
        print_results(results)
        
        if args.output:
            # Save results to JSON file
            output_data = {
                'total_captured_flags': results['total_captured_flags'],
                'total_unique_instances': results['total_unique_instances'],
                'total_successful_trajectories': results['total_successful_trajectories'],
                'success_rate': results['success_rate'],
                'folder_results': results['folder_results'],
                'all_unique_instances': list(results['all_unique_instances']),
                'all_captured_instances': list(results['all_captured_instances']),
                'step_statistics': results['step_statistics'],
                'top_5_shortest_trajectories': [
                    {
                        'instance_id': instance_id,
                        'step_count': step_count,
                        'folder_path': folder_path,
                        'traj_file_path': str(Path(folder_path) / f"{instance_id}.traj")
                    }
                    for instance_id, step_count, folder_path in results['top_5_shortest_trajectories']
                ]
            }
            
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            print(f"\nResults saved to: {args.output}")
            
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main()) 