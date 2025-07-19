#!/usr/bin/env python3
"""
Script to compare two instance-by-type JSON files and analyze overlap distribution.

This script:
1. Loads two JSON files with instance IDs categorized by type
2. Compares the instances to find overlaps and differences
3. Provides overall and per-type overlap statistics
4. Shows which instances are unique to each dataset
"""

import json
import argparse
from pathlib import Path
from typing import Dict, Set, Tuple


def load_instances_by_type(file_path: str) -> Dict:
    """
    Load instances by type from a JSON file.
    
    Args:
        file_path: Path to the JSON file
        
    Returns:
        Dictionary with instances categorized by type
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise ValueError(f"Error loading {file_path}: {e}")


def analyze_overlap(data1: Dict, data2: Dict) -> Dict:
    """
    Analyze overlap between two instance-by-type datasets.
    
    Args:
        data1: First dataset
        data2: Second dataset
        
    Returns:
        Dictionary with overlap analysis results
    """
    results = {
        'overall': {
            'total_instances_1': 0,
            'total_instances_2': 0,
            'overlapping_instances': 0,
            'unique_to_1': 0,
            'unique_to_2': 0,
            'overlap_rate_1': 0.0,
            'overlap_rate_2': 0.0
        },
        'by_type': {},
        'overlapping_instances': set(),
        'unique_to_1': set(),
        'unique_to_2': set()
    }
    
    # Get all instance sets
    all_instances_1 = set()
    all_instances_2 = set()
    
    # Collect all instances from both datasets
    for challenge_type, type_data in data1.items():
        # Handle both old format (all_instances) and new format (captured_instances only)
        if 'all_instances' in type_data:
            all_instances_1.update(type_data['all_instances'])
        elif 'captured_instances' in type_data:
            all_instances_1.update(type_data['captured_instances'])
    
    for challenge_type, type_data in data2.items():
        # Handle both old format (all_instances) and new format (captured_instances only)
        if 'all_instances' in type_data:
            all_instances_2.update(type_data['all_instances'])
        elif 'captured_instances' in type_data:
            all_instances_2.update(type_data['captured_instances'])
    
    # Calculate overall overlap
    overlapping = all_instances_1 & all_instances_2
    unique_to_1 = all_instances_1 - all_instances_2
    unique_to_2 = all_instances_2 - all_instances_1
    
    results['overall']['total_instances_1'] = len(all_instances_1)
    results['overall']['total_instances_2'] = len(all_instances_2)
    results['overall']['overlapping_instances'] = len(overlapping)
    results['overall']['unique_to_1'] = len(unique_to_1)
    results['overall']['unique_to_2'] = len(unique_to_2)
    results['overall']['overlap_rate_1'] = len(overlapping) / len(all_instances_1) if all_instances_1 else 0.0
    results['overall']['overlap_rate_2'] = len(overlapping) / len(all_instances_2) if all_instances_2 else 0.0
    
    results['overlapping_instances'] = overlapping
    results['unique_to_1'] = unique_to_1
    results['unique_to_2'] = unique_to_2
    
    # Analyze by type
    all_types = set(data1.keys()) | set(data2.keys())
    
    for challenge_type in all_types:
        type_data_1 = data1.get(challenge_type, {})
        type_data_2 = data2.get(challenge_type, {})
        
        # Handle both old and new formats
        instances_1 = set()
        if 'all_instances' in type_data_1:
            instances_1 = set(type_data_1['all_instances'])
        elif 'captured_instances' in type_data_1:
            instances_1 = set(type_data_1['captured_instances'])
        
        instances_2 = set()
        if 'all_instances' in type_data_2:
            instances_2 = set(type_data_2['all_instances'])
        elif 'captured_instances' in type_data_2:
            instances_2 = set(type_data_2['captured_instances'])
        
        type_overlapping = instances_1 & instances_2
        type_unique_to_1 = instances_1 - instances_2
        type_unique_to_2 = instances_2 - instances_1
        
        results['by_type'][challenge_type] = {
            'total_instances_1': len(instances_1),
            'total_instances_2': len(instances_2),
            'overlapping_instances': len(type_overlapping),
            'unique_to_1': len(type_unique_to_1),
            'unique_to_2': len(type_unique_to_2),
            'overlap_rate_1': len(type_overlapping) / len(instances_1) if instances_1 else 0.0,
            'overlap_rate_2': len(type_overlapping) / len(instances_2) if instances_2 else 0.0,
            'overlapping_list': sorted(list(type_overlapping)),
            'unique_to_1_list': sorted(list(type_unique_to_1)),
            'unique_to_2_list': sorted(list(type_unique_to_2))
        }
    
    return results


def print_results(results: Dict, file1_name: str, file2_name: str, show_details: bool = False):
    """Print the comparison results in a formatted way."""
    print("\n" + "="*60)
    print("INSTANCE OVERLAP ANALYSIS")
    print("="*60)
    
    print(f"\nFile 1: {file1_name}")
    print(f"File 2: {file2_name}")
    
    # Overall statistics
    overall = results['overall']
    print(f"\nOverall Statistics:")
    print("-" * 40)
    print(f"  Total instances in File 1: {overall['total_instances_1']}")
    print(f"  Total instances in File 2: {overall['total_instances_2']}")
    print(f"  Overlapping instances: {overall['overlapping_instances']}")
    print(f"  Unique to File 1: {overall['unique_to_1']}")
    print(f"  Unique to File 2: {overall['unique_to_2']}")
    print(f"  Overlap rate (File 1): {overall['overlap_rate_1']:.1%}")
    print(f"  Overlap rate (File 2): {overall['overlap_rate_2']:.1%}")
    
    # By type statistics
    print(f"\nOverlap by Challenge Type:")
    print("-" * 40)
    
    # Sort types by total instances (descending)
    sorted_types = sorted(
        results['by_type'].items(),
        key=lambda x: x[1]['total_instances_1'] + x[1]['total_instances_2'],
        reverse=True
    )
    
    for challenge_type, type_stats in sorted_types:
        print(f"  {challenge_type}:")
        print(f"    File 1: {type_stats['total_instances_1']} instances")
        print(f"    File 2: {type_stats['total_instances_2']} instances")
        print(f"    Overlapping: {type_stats['overlapping_instances']} instances")
        print(f"    Unique to File 1: {type_stats['unique_to_1']} instances")
        print(f"    Unique to File 2: {type_stats['unique_to_2']} instances")
        print(f"    Overlap rate (File 1): {type_stats['overlap_rate_1']:.1%}")
        print(f"    Overlap rate (File 2): {type_stats['overlap_rate_2']:.1%}")
        print()
    
    # Show detailed instance lists if requested
    if show_details:
        print(f"\nDetailed Instance Lists:")
        print("="*60)
        
        for challenge_type, type_stats in sorted_types:
            if type_stats['overlapping_instances'] > 0 or type_stats['unique_to_1'] > 0 or type_stats['unique_to_2'] > 0:
                print(f"\n{challenge_type.upper()}:")
                print("-" * 40)
                
                if type_stats['overlapping_instances'] > 0:
                    print(f"  Overlapping instances ({type_stats['overlapping_instances']}):")
                    for instance in type_stats['overlapping_list']:
                        print(f"    {instance}")
                
                if type_stats['unique_to_1'] > 0:
                    print(f"  Unique to File 1 ({type_stats['unique_to_1']}):")
                    for instance in type_stats['unique_to_1_list']:
                        print(f"    {instance}")
                
                if type_stats['unique_to_2'] > 0:
                    print(f"  Unique to File 2 ({type_stats['unique_to_2']}):")
                    for instance in type_stats['unique_to_2_list']:
                        print(f"    {instance}")


def main():
    parser = argparse.ArgumentParser(
        description="Compare two instance-by-type JSON files and analyze overlap distribution"
    )
    parser.add_argument(
        "file1",
        help="Path to the first JSON file with instances by type"
    )
    parser.add_argument(
        "file2",
        help="Path to the second JSON file with instances by type"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file to save comparison results as JSON (optional)"
    )
    parser.add_argument(
        "--show_details",
        action="store_true",
        help="Show detailed instance lists (disabled by default)"
    )
    
    args = parser.parse_args()
    
    try:
        # Load both files
        data1 = load_instances_by_type(args.file1)
        data2 = load_instances_by_type(args.file2)
        
        # Analyze overlap
        results = analyze_overlap(data1, data2)
        
        # Print results
        print_results(results, args.file1, args.file2, args.show_details)
        
        # Save results if requested
        if args.output:
            # Prepare output data (convert sets to lists for JSON serialization)
            output_data = {
                'file1': args.file1,
                'file2': args.file2,
                'overall': results['overall'],
                'by_type': results['by_type'],
                'overlapping_instances': sorted(list(results['overlapping_instances'])),
                'unique_to_1': sorted(list(results['unique_to_1'])),
                'unique_to_2': sorted(list(results['unique_to_2']))
            }
            
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            print(f"\nComparison results saved to: {args.output}")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main()) 