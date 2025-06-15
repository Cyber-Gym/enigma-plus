#!/usr/bin/env python3
"""
Test script to demonstrate how SummarizeFunction objects are displayed
"""

import yaml
from sweagent.agent.summarizer import SummarizerConfig

# Test the summarizer configuration
config = SummarizerConfig(
    function="SimpleSummarizer",
    window_length=105,
    system_template="Test system template",
    instance_template="Test instance template"
)

print("Before processing:")
print(f"function (string): {config._original_function_name}")

print("\nAfter processing:")
print(f"function (object): {config.function}")
print(f"function.__repr__(): {repr(config.function)}")
print(f"function_name property: {config.function_name}")

print("\nYAML representation:")
yaml_output = yaml.dump({"summarizer_config": config.__dict__})
print(yaml_output)

# Test with different summarizer types
print("\n" + "="*50)
print("Testing different summarizer types:")

for func_name in ["Identity", "SimpleSummarizer", "LMSummarizer"]:
    try:
        config = SummarizerConfig(function=func_name, window_length=105)
        print(f"\n{func_name}:")
        print(f"  Original name: {config._original_function_name}")
        print(f"  Object repr: {repr(config.function)}")
        print(f"  Property: {config.function_name}")
        
        # Test YAML serialization
        yaml_data = yaml.dump({"function": config.function})
        print(f"  YAML output: {yaml_data.strip()}")
        
    except Exception as e:
        print(f"  Error with {func_name}: {e}") 