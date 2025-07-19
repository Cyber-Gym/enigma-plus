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


def analyze_trajectory_folder(folder_path: str) -> Tuple[int, Set[str], Set[str], int, List[Tuple[str, int]], Dict]:
    """
    Analyze a single trajectory folder to count captured flags and unique instances.
    
    Args:
        folder_path: Path to the trajectory folder
        
    Returns:
        Tuple of (captured_flags_count, unique_instance_ids, captured_instance_ids, total_successful_trajectories, step_data, type_stats)
    """
    captured_instances = set()
    unique_instances = set()
    successful_trajectories = 0
    step_data = []  # List of (instance_id, step_count) tuples
    type_stats = {}  # Dictionary to track statistics by challenge type
    
    # Look for all_preds.jsonl file in the folder
    preds_file = Path(folder_path) / "all_preds.jsonl"
    
    if not preds_file.exists():
        print(f"Warning: No all_preds.jsonl found in {folder_path}")
        return 0, set(), set(), 0, [], {}
    
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
                        
                        # Extract challenge type from instance_id (before underscore)
                        challenge_type = instance_id.split('_')[0] if '_' in instance_id else 'unknown'
                        
                        # Initialize type stats if not exists
                        if challenge_type not in type_stats:
                            type_stats[challenge_type] = {
                                'total_instances': set(),  # Use set to track unique instances
                                'captured_instances': set(),  # Use set to track unique instances
                                'successful_trajectories': 0,
                                'step_counts': []
                            }
                        
                        type_stats[challenge_type]['total_instances'].add(instance_id)
                        
                        # Check if flag was captured (model_patch is not null and is a string)
                        if model_patch is not None and isinstance(model_patch, str):
                            captured_instances.add(instance_id)
                            successful_trajectories += 1
                            type_stats[challenge_type]['captured_instances'].add(instance_id)
                            type_stats[challenge_type]['successful_trajectories'] += 1
                            
                            # Load trajectory file to count steps
                            traj_file = Path(folder_path) / f"{instance_id}.traj"
                            if traj_file.exists():
                                try:
                                    with open(traj_file, 'r', encoding='utf-8') as traj_f:
                                        traj_data = json.load(traj_f)
                                        trajectory = traj_data.get('trajectory', [])
                                        step_count = len(trajectory)
                                        step_data.append((instance_id, step_count))
                                        type_stats[challenge_type]['step_counts'].append(step_count)
                                except Exception as e:
                                    print(f"Warning: Could not read trajectory file {traj_file}: {e}")
                                    # Add 0 steps for this trajectory if we can't read it
                                    step_data.append((instance_id, 0))
                                    type_stats[challenge_type]['step_counts'].append(0)
                            else:
                                print(f"Warning: No trajectory file found for successful instance {instance_id}")
                                # Add 0 steps for this trajectory if file doesn't exist
                                step_data.append((instance_id, 0))
                                type_stats[challenge_type]['step_counts'].append(0)
                            
                except json.JSONDecodeError as e:
                    print(f"Warning: Invalid JSON on line {line_num} in {preds_file}: {e}")
                    continue
                    
    except Exception as e:
        print(f"Error reading {preds_file}: {e}")
        return 0, set(), set(), 0, [], {}
    
    return len(captured_instances), unique_instances, captured_instances, successful_trajectories, step_data, type_stats


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
    overall_type_stats = {}  # Aggregate type statistics across all folders
    instance_success_frequency = {}  # Track how many times each instance succeeds
    
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
            'top_5_shortest_trajectories': [],
            'type_distribution': {},
            'instance_success_frequency': {}
        }
    
    print(f"Found {len(model_folders)} model result folders with all_preds.jsonl")
    
    for folder in model_folders:
        # Create a descriptive folder name using the relative path
        relative_path = folder.relative_to(root_path)
        folder_name = str(relative_path).replace('/', '_')
        
        print(f"Analyzing {folder_name}...")
        
        captured_count, unique_instances, captured_instances, successful_trajectories, step_data, type_stats = analyze_trajectory_folder(str(folder))
        
        # Track instance success frequency
        for instance_id in captured_instances:
            if instance_id not in instance_success_frequency:
                instance_success_frequency[instance_id] = 0
            instance_success_frequency[instance_id] += 1
        
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
            'step_statistics': folder_step_stats,
            'type_stats': type_stats
        }
        
        # Aggregate type statistics
        for challenge_type, stats in type_stats.items():
            if challenge_type not in overall_type_stats:
                overall_type_stats[challenge_type] = {
                    'total_instances': set(),
                    'captured_instances': set(),
                    'successful_trajectories': 0,
                    'step_counts': []
                }
            
            overall_type_stats[challenge_type]['total_instances'].update(stats['total_instances'])
            overall_type_stats[challenge_type]['captured_instances'].update(stats['captured_instances'])
            overall_type_stats[challenge_type]['successful_trajectories'] += stats['successful_trajectories']
            overall_type_stats[challenge_type]['step_counts'].extend(stats['step_counts'])
        
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
    
    # Calculate type distribution statistics
    type_distribution = {}
    for challenge_type, stats in overall_type_stats.items():
        success_rate = len(stats['captured_instances']) / len(stats['total_instances']) if len(stats['total_instances']) > 0 else 0.0
        
        type_distribution[challenge_type] = {
            'total_instances': len(stats['total_instances']),
            'captured_instances': len(stats['captured_instances']),
            'successful_trajectories': stats['successful_trajectories'],
            'success_rate': success_rate,
            'step_statistics': {}
        }
        
        if stats['step_counts']:
            type_distribution[challenge_type]['step_statistics'] = {
                'average_steps': statistics.mean(stats['step_counts']),
                'median_steps': statistics.median(stats['step_counts']),
                'min_steps': min(stats['step_counts']),
                'max_steps': max(stats['step_counts']),
                'total_trajectories': len(stats['step_counts'])
            }
    
    return {
        'total_captured_flags': total_captured_flags,
        'total_unique_instances': total_unique_instances,
        'total_successful_trajectories': total_successful_trajectories,
        'success_rate': overall_success_rate,
        'folder_results': folder_results,
        'all_unique_instances': all_unique_instances,
        'all_captured_instances': all_captured_instances,
        'step_statistics': overall_step_stats,
        'top_5_shortest_trajectories': top_5_shortest,
        'type_distribution': type_distribution,
        'instance_success_frequency': instance_success_frequency
    }


def print_results(results: Dict, show_per_model: bool = False):
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
    
    # Print type distribution
    type_distribution = results['type_distribution']
    if type_distribution:
        # Print simple success rate distribution summary
        print(f"\nSuccess Rate Distribution by Type:")
        print("-" * 40)
        
        # Sort types by success rate (descending)
        sorted_types_by_success = sorted(type_distribution.items(), key=lambda x: x[1]['success_rate'], reverse=True)
        
        for challenge_type, stats in sorted_types_by_success:
            print(f"  {challenge_type}: {stats['success_rate']:.1%}")
    else:
        print(f"\nType Distribution: No data available")
    
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
    
    # Print success frequency summary
    frequency_data = results.get('instance_success_frequency', {})
    if frequency_data:
        print(f"\nSuccess Frequency Summary:")
        print("-" * 40)
        
        # Calculate frequency statistics
        frequencies = list(frequency_data.values())
        max_freq = max(frequencies) if frequencies else 0
        min_freq = min(frequencies) if frequencies else 0
        avg_freq = statistics.mean(frequencies) if frequencies else 0
        median_freq = statistics.median(frequencies) if frequencies else 0
        
        # Calculate skewness
        if len(frequencies) > 2:
            # Calculate sample standard deviation
            variance = statistics.variance(frequencies)
            std_dev = variance ** 0.5
            
            # Calculate skewness using the formula: E[(X-μ)³] / σ³
            skewness = 0
            for freq in frequencies:
                skewness += ((freq - avg_freq) ** 3)
            skewness = skewness / (len(frequencies) * (std_dev ** 3))
        else:
            skewness = 0
        
        print(f"  Total successful instances: {len(frequency_data)}")
        print(f"  Maximum success frequency: {max_freq}")
        print(f"  Minimum success frequency: {min_freq}")
        print(f"  Average success frequency: {avg_freq:.1f}")
        print(f"  Median success frequency: {median_freq:.1f}")
        print(f"  Skewness: {skewness:.3f}")
        
        # Interpret skewness
        if abs(skewness) < 0.5:
            skew_interpretation = "approximately symmetric"
        elif skewness > 0.5:
            skew_interpretation = "right-skewed (few instances with high frequency)"
        else:
            skew_interpretation = "left-skewed (many instances with low frequency)"
        print(f"  Distribution: {skew_interpretation}")
        
        # Show top 10 most frequently successful instances
        sorted_frequency = sorted(frequency_data.items(), key=lambda x: x[1], reverse=True)
        print(f"\nTop 10 Most Frequently Successful Instances:")
        print("-" * 50)
        for i, (instance_id, count) in enumerate(sorted_frequency[:10], 1):
            challenge_type = instance_id.split('_')[0] if '_' in instance_id else 'unknown'
            print(f"  {i:2d}. {instance_id} ({challenge_type}): {count} times")
    else:
        print(f"\nSuccess Frequency Summary: No successful instances found")
    
    # Print per-model breakdown only if requested
    if show_per_model:
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
            
            # Print type statistics for this folder
            folder_type_stats = folder_data['type_stats']
            if folder_type_stats:
                print(f"  Type Statistics:")
                for challenge_type, stats in folder_type_stats.items():
                    print(f"    Challenge Type '{challenge_type}':")
                    print(f"      Total Instances: {len(stats['total_instances'])}")
                    print(f"      Captured Instances: {len(stats['captured_instances'])}")
                    print(f"      Successful Trajectories: {stats['successful_trajectories']}")
                    if stats['step_counts']:
                        print(f"      Average Steps: {statistics.mean(stats['step_counts']):.1f}")
                        print(f"      Median Steps: {statistics.median(stats['step_counts']):.1f}")
                        print(f"      Min Steps: {min(stats['step_counts'])}")
                        print(f"      Max Steps: {max(stats['step_counts'])}")
                        print(f"      Total Trajectories: {len(stats['step_counts'])}")
                    else:
                        print(f"      No successful trajectories for this type.")
            
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
    parser.add_argument(
        "--show_per_model",
        action="store_true",
        help="Show detailed per-model breakdown (disabled by default)"
    )
    parser.add_argument(
        "--instances_by_type",
        help="Output file to save instance IDs categorized by type (optional)"
    )
    parser.add_argument(
        "--success_frequency",
        help="Output file to save sorted success frequency data (optional)"
    )
    
    args = parser.parse_args()
    
    try:
        results = analyze_trajectories_root(args.path)
        print_results(results, args.show_per_model)
        
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
                ],
                'type_distribution': results['type_distribution'],
                'instance_success_frequency': results['instance_success_frequency']
            }
            
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            print(f"\nResults saved to: {args.output}")
        
        if args.instances_by_type:
            # Create instances by type data (only successful instances)
            instances_by_type = {}
            
            # Get only captured instances and categorize them by type
            captured_instances = results['all_captured_instances']
            
            for instance_id in captured_instances:
                # Extract challenge type from instance_id (before underscore)
                challenge_type = instance_id.split('_')[0] if '_' in instance_id else 'unknown'
                
                if challenge_type not in instances_by_type:
                    instances_by_type[challenge_type] = {
                        'captured_instances': []
                    }
                
                instances_by_type[challenge_type]['captured_instances'].append(instance_id)
            
            # Sort instances within each type for consistency
            for challenge_type in instances_by_type:
                instances_by_type[challenge_type]['captured_instances'].sort()
            
            with open(args.instances_by_type, 'w', encoding='utf-8') as f:
                json.dump(instances_by_type, f, indent=2, ensure_ascii=False)
            
            print(f"Successful instances by type saved to: {args.instances_by_type}")
        
        if args.success_frequency:
            # Create sorted success frequency data
            frequency_data = results['instance_success_frequency']
            
            # Convert to list of tuples and sort by frequency (descending)
            sorted_frequency = sorted(frequency_data.items(), key=lambda x: x[1], reverse=True)
            
            # Calculate skewness for JSON output
            frequencies = list(frequency_data.values())
            skewness = 0
            if len(frequencies) > 2:
                avg_freq = statistics.mean(frequencies)
                variance = statistics.variance(frequencies)
                std_dev = variance ** 0.5
                
                # Calculate skewness using the formula: E[(X-μ)³] / σ³
                for freq in frequencies:
                    skewness += ((freq - avg_freq) ** 3)
                skewness = skewness / (len(frequencies) * (std_dev ** 3))
            
            # Create output structure
            success_frequency_output = {
                'total_folders_analyzed': len(results['folder_results']),
                'total_unique_instances': results['total_unique_instances'],
                'total_successful_instances': len(frequency_data),
                'frequency_statistics': {
                    'max_frequency': max(frequencies) if frequencies else 0,
                    'min_frequency': min(frequencies) if frequencies else 0,
                    'average_frequency': statistics.mean(frequencies) if frequencies else 0,
                    'median_frequency': statistics.median(frequencies) if frequencies else 0,
                    'skewness': skewness,
                    'distribution_type': 'approximately symmetric' if abs(skewness) < 0.5 else ('right-skewed' if skewness > 0.5 else 'left-skewed')
                },
                'frequency_distribution': [
                    {
                        'instance_id': instance_id,
                        'success_count': count,
                        'challenge_type': instance_id.split('_')[0] if '_' in instance_id else 'unknown'
                    }
                    for instance_id, count in sorted_frequency
                ]
            }
            
            with open(args.success_frequency, 'w', encoding='utf-8') as f:
                json.dump(success_frequency_output, f, indent=2, ensure_ascii=False)
            
            print(f"Success frequency data saved to: {args.success_frequency}")
            
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main()) 