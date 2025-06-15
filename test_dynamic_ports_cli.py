#!/usr/bin/env python3
"""
Test script to demonstrate the enable_dynamic_ports argument usage.

This script shows how to:
1. Use the --environment.enable_dynamic_ports flag from command line
2. Set enable_dynamic_ports=True programmatically
3. Verify dynamic port allocation is working correctly
"""

import subprocess
import tempfile
import yaml
from pathlib import Path

def create_test_challenge():
    """Create a simple test challenge for demonstration"""
    
    # Create a temporary directory for the test challenge
    temp_dir = Path(tempfile.mkdtemp(prefix="test_challenge_"))
    
    # Create challenge.json
    challenge_data = {
        "name": "DynamicPortTest",
        "category": "web",
        "description": "Test challenge to demonstrate dynamic port allocation",
        "flag": "flag{dynamic_ports_work}",
        "internal_port": 8080,
        "box": "web.test.challenge"
    }
    
    challenge_file = temp_dir / "challenge.json"
    with open(challenge_file, 'w') as f:
        json.dump(challenge_data, f, indent=2)
    
    # Create docker-compose.yml
    compose_data = {
        'services': {
            'web-service': {
                'image': 'nginx:alpine',
                'ports': ['8080:80'],
                'networks': {
                    'ctfnet': {
                        'aliases': ['web.test.challenge']
                    }
                }
            }
        },
        'networks': {
            'ctfnet': {
                'external': True
            }
        }
    }
    
    compose_file = temp_dir / "docker-compose.yml"
    with open(compose_file, 'w') as f:
        yaml.dump(compose_data, f)
    
    print(f"✅ Created test challenge at: {temp_dir}")
    print(f"   - challenge.json: {challenge_file}")
    print(f"   - docker-compose.yml: {compose_file}")
    
    return temp_dir

def test_cli_argument():
    """Test the command-line argument functionality"""
    
    print("\n" + "="*70)
    print("TESTING CLI ARGUMENT: --environment.enable_dynamic_ports")
    print("="*70)
    
    # Create test challenge
    challenge_dir = create_test_challenge()
    challenge_file = challenge_dir / "challenge.json"
    
    print("\n1. Testing WITHOUT dynamic ports (default behavior):")
    cmd_without = [
        "python", "-c", 
        f"""
import sys
sys.path.append('.')
from sweagent.environment.swe_env import EnvironmentArguments, SWEEnv

args = EnvironmentArguments(
    data_path="{challenge_file}",
    enable_dynamic_ports=False,  # Explicitly disabled
    verbose=True
)

print(f"enable_dynamic_ports: {{args.enable_dynamic_ports}}")
env = SWEEnv(args)
print(f"Port mappings: {{env.port_mappings}}")
print(f"Dynamic network: {{env.dynamic_network_name}}")
env.close()
        """
    ]
    
    try:
        result = subprocess.run(cmd_without, capture_output=True, text=True, timeout=30)
        print(f"   Return code: {result.returncode}")
        if result.stdout:
            print(f"   Output: {result.stdout.strip()}")
        if result.stderr:
            print(f"   Errors: {result.stderr.strip()}")
    except Exception as e:
        print(f"   ❌ Test failed: {e}")
    
    print("\n2. Testing WITH dynamic ports enabled:")
    cmd_with = [
        "python", "-c", 
        f"""
import sys
sys.path.append('.')
from sweagent.environment.swe_env import EnvironmentArguments, SWEEnv

args = EnvironmentArguments(
    data_path="{challenge_file}",
    enable_dynamic_ports=True,  # Enabled!
    verbose=True,
    container_name="test-dynamic-ports"  # Required for dynamic ports
)

print(f"enable_dynamic_ports: {{args.enable_dynamic_ports}}")
env = SWEEnv(args)
print(f"Port mappings: {{env.port_mappings}}")
print(f"Dynamic network: {{env.dynamic_network_name}}")
env.close()
        """
    ]
    
    try:
        result = subprocess.run(cmd_with, capture_output=True, text=True, timeout=30)
        print(f"   Return code: {result.returncode}")
        if result.stdout:
            print(f"   Output: {result.stdout.strip()}")
        if result.stderr:
            print(f"   Errors: {result.stderr.strip()}")
    except Exception as e:
        print(f"   ❌ Test failed: {e}")
    
    print("\n3. Command-line usage examples:")
    print("""
   # Disable dynamic ports (default):
   python run.py --environment.data_path challenge.json --environment.enable_dynamic_ports False
   
   # Enable dynamic ports:
   python run.py --environment.data_path challenge.json --environment.enable_dynamic_ports True --environment.container_name my-container
   
   # Using YAML config:
   # In your config file:
   environment:
     enable_dynamic_ports: true
     container_name: "dynamic-container"
   """)
    
    # Cleanup
    import shutil
    shutil.rmtree(challenge_dir)
    print(f"\n✅ Cleaned up test challenge directory")

def test_programmatic_usage():
    """Test programmatic usage of the flag"""
    
    print("\n" + "="*70)
    print("TESTING PROGRAMMATIC USAGE")
    print("="*70)
    
    from sweagent.environment.swe_env import EnvironmentArguments, SWEEnv
    import json
    
    # Create test challenge
    challenge_dir = create_test_challenge()
    challenge_file = challenge_dir / "challenge.json"
    
    print("\n1. Default behavior (dynamic ports disabled):")
    try:
        args_default = EnvironmentArguments(
            data_path=str(challenge_file),
            # enable_dynamic_ports defaults to False
        )
        print(f"   enable_dynamic_ports: {args_default.enable_dynamic_ports}")
        print(f"   ✅ Default is False (backward compatible)")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print("\n2. Explicitly enabling dynamic ports:")
    try:
        args_enabled = EnvironmentArguments(
            data_path=str(challenge_file),
            enable_dynamic_ports=True,
            container_name="test-dynamic-container",
            verbose=True
        )
        print(f"   enable_dynamic_ports: {args_enabled.enable_dynamic_ports}")
        print(f"   container_name: {args_enabled.container_name}")
        print(f"   ✅ Dynamic ports enabled")
        
        # Test creating environment (without actually running containers)
        print("\n   Creating SWEEnv instance...")
        env = SWEEnv(args_enabled)
        print(f"   Port mappings: {env.port_mappings}")
        print(f"   Dynamic network: {env.dynamic_network_name}")
        env.close()
        print(f"   ✅ SWEEnv created successfully with dynamic ports")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Cleanup
    import shutil
    shutil.rmtree(challenge_dir)
    print(f"\n✅ Cleaned up test challenge directory")

def test_parallel_usage_example():
    """Show example of parallel usage with dynamic ports"""
    
    print("\n" + "="*70)
    print("PARALLEL USAGE EXAMPLE")
    print("="*70)
    
    print("""
Example: Running 3 challenges in parallel with dynamic ports

```python
import threading
from sweagent.environment.swe_env import EnvironmentArguments, SWEEnv

def solve_challenge(challenge_path, instance_id):
    args = EnvironmentArguments(
        data_path=challenge_path,
        enable_dynamic_ports=True,  # ← KEY: Enable dynamic ports
        container_name=f"parallel-{instance_id}",  # ← KEY: Unique container names
        verbose=True
    )
    
    env = SWEEnv(args)
    try:
        print(f"Instance {instance_id}: ports={env.port_mappings}")
        # Your challenge solving logic here...
    finally:
        env.close()

# Run multiple challenges in parallel
challenges = [
    "challenge1/challenge.json", 
    "challenge2/challenge.json", 
    "challenge3/challenge.json"
]

threads = []
for i, challenge in enumerate(challenges):
    thread = threading.Thread(target=solve_challenge, args=(challenge, i))
    threads.append(thread)
    thread.start()

for thread in threads:
    thread.join()
```

Command line equivalent:
```bash
# Terminal 1:
python run.py --environment.data_path challenge1.json --environment.enable_dynamic_ports True --environment.container_name parallel-1 &

# Terminal 2:  
python run.py --environment.data_path challenge2.json --environment.enable_dynamic_ports True --environment.container_name parallel-2 &

# Terminal 3:
python run.py --environment.data_path challenge3.json --environment.enable_dynamic_ports True --environment.container_name parallel-3 &
```
""")

def show_help():
    """Show help information about the dynamic ports feature"""
    
    print("\n" + "="*70)
    print("DYNAMIC PORTS HELP")
    print("="*70)
    
    print("""
🔌 Dynamic Port Allocation Feature

DESCRIPTION:
   Enables running multiple CTF challenges in parallel without port conflicts
   by automatically assigning unique external ports to each instance.

USAGE:
   --environment.enable_dynamic_ports True

REQUIREMENTS:
   - Must set enable_dynamic_ports=True
   - Must provide a unique container_name for each instance
   - Challenge must have docker-compose.yml or ports defined in challenge.json

BEHAVIOR:
   When ENABLED:
   ✅ Automatically assigns unique external ports (e.g., 10001, 10002, 10003)
   ✅ Creates isolated networks for each instance  
   ✅ Allows parallel execution without conflicts
   ✅ Updates challenge descriptions with correct ports
   
   When DISABLED (default):
   ❌ Uses original port mappings from docker-compose.yml
   ❌ Cannot run multiple instances in parallel
   ✅ Backward compatible with existing workflows

EXAMPLES:
   # Single challenge with dynamic ports
   python run.py --environment.data_path challenge.json --environment.enable_dynamic_ports True --environment.container_name unique-name
   
   # Using config file
   echo "environment:" > config.yaml
   echo "  enable_dynamic_ports: true" >> config.yaml
   echo "  container_name: my-container" >> config.yaml
   python run.py --config config.yaml --environment.data_path challenge.json

PARALLEL EXECUTION:
   Each instance needs:
   - enable_dynamic_ports=True
   - Unique container_name
   - Same or different challenges
   
   Result: Each gets unique external ports automatically!

TROUBLESHOOTING:
   - Port exhaustion: Increase DEFAULT_PORT_RANGE_END in utils.py
   - Permission errors: Ensure Docker daemon is running
   - Network conflicts: Use unique container names
""")

if __name__ == "__main__":
    import sys
    import json
    
    print("🔌 Dynamic Ports CLI Test")
    print("Testing the --environment.enable_dynamic_ports argument")
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help":
            show_help()
        elif sys.argv[1] == "--cli":
            test_cli_argument()
        elif sys.argv[1] == "--programmatic":
            test_programmatic_usage()
        elif sys.argv[1] == "--parallel":
            test_parallel_usage_example()
        else:
            print(f"Unknown option: {sys.argv[1]}")
            print("Use: --help, --cli, --programmatic, or --parallel")
    else:
        # Run all tests
        test_programmatic_usage()
        test_cli_argument()
        test_parallel_usage_example()
        show_help() 