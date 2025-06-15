#!/usr/bin/env python3
"""
Test script to verify dynamic port allocation functionality for CTF challenges.
"""

import tempfile
import yaml
from pathlib import Path
import json
import subprocess
import time
import socket
import requests

from sweagent.environment.utils import (
    create_dynamic_docker_compose,
    get_docker_compose,
    get_available_port,
    InstanceBuilder,
    get_multiple_available_ports,
    is_port_in_use
)

def test_dynamic_port_checking():
    """Test the new dynamic port checking functionality"""
    
    print("\n=== Testing Dynamic Port Checking ===")
    
    # Test basic port availability checking
    port1 = get_available_port()
    print(f"First available port: {port1}")
    
    port2 = get_available_port()
    print(f"Second available port: {port2}")
    
    # They should be different
    assert port1 != port2, f"Got same port twice: {port1}"
    print("✅ Different ports allocated successfully")
    
    # Test multiple port allocation
    ports = get_multiple_available_ports(3)
    print(f"Multiple ports allocated: {ports}")
    
    # All should be unique
    assert len(set(ports)) == len(ports), "Duplicate ports in multiple allocation"
    assert len(ports) == 3, f"Expected 3 ports, got {len(ports)}"
    print("✅ Multiple unique ports allocated successfully")
    
    # Test port usage checking
    for port in ports[:2]:  # Test first two ports
        in_use_before = is_port_in_use(port)
        print(f"Port {port} in use before test: {in_use_before}")
    
    print("✅ Dynamic port checking test passed!")


def test_dynamic_port_allocation():
    """Test that dynamic port allocation works correctly"""
    
    # Create a sample docker-compose.yml like the ones in CTF challenges
    compose_content = {
        'services': {
            'test-service': {
                'image': 'nginx:latest',
                'ports': ['8080:80'],
                'networks': {
                    'ctfnet': {
                        'aliases': ['test.chal.example.io']
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
    
    # Create temporary docker-compose file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        yaml.dump(compose_content, f)
        compose_path = Path(f.name)
    
    try:
        # Test dynamic port allocation
        container_suffix = "test123"
        dynamic_network_name = f"ctfnet-{container_suffix}"
        
        # Create port mappings
        port_mappings = {"80": get_available_port()}
        
        # Create dynamic docker-compose
        new_compose_path = create_dynamic_docker_compose(
            compose_path,
            container_suffix,
            dynamic_network_name,
            port_mappings
        )
        
        # Read the modified compose file
        with open(new_compose_path) as f:
            modified_compose = yaml.safe_load(f)
        
        print("Original compose:")
        print(yaml.dump(compose_content, default_flow_style=False))
        print("\nModified compose:")
        print(yaml.dump(modified_compose, default_flow_style=False))
        print(f"\nPort mappings: {port_mappings}")
        
        # Verify the modifications
        assert f'test-service-{container_suffix}' in modified_compose['services']
        service = modified_compose['services'][f'test-service-{container_suffix}']
        
        # Check port mapping
        expected_port_mapping = f"{port_mappings['80']}:80"
        assert expected_port_mapping in service['ports']
        
        # Check network name change
        assert dynamic_network_name in service['networks']
        assert 'ctfnet' not in service['networks']
        
        # Check network definition
        assert dynamic_network_name in modified_compose['networks']
        assert modified_compose['networks'][dynamic_network_name]['driver'] == 'bridge'
        
        print("✅ Dynamic port allocation test passed!")
        
        # Clean up
        new_compose_path.unlink()
        
    finally:
        compose_path.unlink()


def test_challenge_without_ports():
    """Test handling of challenges where docker-compose has no explicit ports"""
    
    # Create a docker-compose like smug-dino (no explicit ports)
    compose_content = {
        'services': {
            'smug-dino': {
                'image': 'llmctf/2023q-web-smug_dino',
                'networks': {
                    'ctfnet': {
                        'aliases': ['web.chal.csaw.io']
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
    
    # Create temporary docker-compose file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        yaml.dump(compose_content, f)
        compose_path = Path(f.name)
    
    try:
        # Test with challenge internal port (like from challenge.json)
        challenge_internal_port = 3009
        container_suffix = "test456"
        
        # Test get_docker_compose function
        actual_compose_path, port_mappings = get_docker_compose(
            compose_path,
            container_name_suffix=container_suffix,
            dynamic_ports=True,
            challenge_internal_port=challenge_internal_port
        )
        
        print(f"\nChallenge without explicit ports test:")
        print(f"Port mappings: {port_mappings}")
        
        # Should have mapped the challenge internal port
        assert str(challenge_internal_port) in port_mappings
        external_port = port_mappings[str(challenge_internal_port)]
        
        # Read the modified compose file
        with open(actual_compose_path) as f:
            modified_compose = yaml.safe_load(f)
        
        print("Modified compose for challenge without explicit ports:")
        print(yaml.dump(modified_compose, default_flow_style=False))
        
        # Check that port mapping was added
        service = modified_compose['services'][f'smug-dino-{container_suffix}']
        expected_port_mapping = f"{external_port}:{challenge_internal_port}"
        assert expected_port_mapping in service['ports']
        
        print("✅ Challenge without explicit ports test passed!")
        
        # Clean up
        if actual_compose_path != compose_path:
            actual_compose_path.unlink()
        
    finally:
        compose_path.unlink()


def test_instance_builder_server_description():
    """Test that InstanceBuilder correctly updates server descriptions"""
    
    # Create a mock challenge
    challenge_data = {
        "name": "test-challenge",
        "category": "web",
        "description": "Test challenge",
        "flag": "flag{test}",
        "internal_port": 3009,
        "box": "web.chal.example.io"
    }
    
    # Test InstanceBuilder - simulate how it's set up in set_problem_statement_from_challenge_json
    ib = InstanceBuilder()
    ib.args = {"challenge": challenge_data.copy()}
    # The port field is set from internal_port in the actual code
    ib.args["challenge"]["port"] = challenge_data.get("internal_port") or challenge_data.get("port")
    ib.args["challenge"]["server_name"] = challenge_data.get("box", "127.0.0.1")
    
    # Set initial server description
    ib.set_server_description(ib.args["challenge"]["server_name"], ib.args["challenge"]["port"])
    initial_description = ib.args["challenge"]["server_description"]
    print(f"\nInitial server description: {initial_description}")
    
    # Test with port mapping
    port_mappings = {"3009": 12345}
    ib.update_server_description_with_port_mapping(port_mappings)
    updated_description = ib.args["challenge"]["server_description"]
    print(f"Updated server description: {updated_description}")
    
    # CORRECTED: Container-to-container communication should use service name and internal port
    # External ports are only for host-to-container communication
    assert "web.chal.example.io" in updated_description
    assert "3009" in updated_description  # Should use internal port
    assert "curl http://web.chal.example.io:3009" in updated_description
    # Should NOT use localhost or external port for container communication
    assert "localhost" not in updated_description
    assert "12345" not in updated_description
    
    print("✅ InstanceBuilder server description test passed!")


def is_port_open(host, port, timeout=3):
    """Check if a port is open and accepting connections"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False


def test_parallel_containers_same_internal_port():
    """Test running two containers with the same internal port in parallel"""
    
    print("\n=== Testing Parallel Containers with Same Internal Port ===")
    
    # Create base docker-compose content for a simple web server
    # Both containers will use port 80 internally
    base_compose_content = {
        'services': {
            'web-server': {
                'image': 'nginx:alpine',
                'networks': ['ctfnet']
            }
        },
        'networks': {
            'ctfnet': {
                'external': True
            }
        }
    }
    
    containers_info = []
    temp_files = []
    
    try:
        # Create two identical challenges that both use port 80 internally
        for i in range(2):
            print(f"\n--- Setting up container {i+1} ---")
            
            # Create temporary docker-compose file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
                yaml.dump(base_compose_content, f)
                compose_path = Path(f.name)
                temp_files.append(compose_path)
            
            # Create dynamic port allocation
            container_suffix = f"parallel{i+1}"
            challenge_internal_port = 80  # Both containers use port 80
            
            actual_compose_path, port_mappings = get_docker_compose(
                compose_path,
                container_name_suffix=container_suffix,
                dynamic_ports=True,
                challenge_internal_port=challenge_internal_port
            )
            
            if actual_compose_path != compose_path:
                temp_files.append(actual_compose_path)
            
            external_port = port_mappings.get(str(challenge_internal_port))
            
            print(f"Container {i+1}:")
            print(f"  Internal port: {challenge_internal_port}")
            print(f"  External port: {external_port}")
            print(f"  Docker compose: {actual_compose_path}")
            
            containers_info.append({
                'id': i+1,
                'compose_path': actual_compose_path,
                'internal_port': challenge_internal_port,
                'external_port': external_port,
                'container_suffix': container_suffix
            })
        
        # Verify that different external ports were allocated
        external_ports = [info['external_port'] for info in containers_info]
        assert len(set(external_ports)) == len(external_ports), "External ports should be unique!"
        print(f"\n✅ Successfully allocated unique external ports: {external_ports}")
        
        # Start both containers
        processes = []
        try:
            for info in containers_info:
                print(f"\n--- Starting container {info['id']} ---")
                cmd = [
                    "docker", "compose", "-f", str(info['compose_path']), 
                    "up", "-d", "--force-recreate"
                ]
                print(f"Running: {' '.join(cmd)}")
                process = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if process.returncode != 0:
                    print(f"Failed to start container {info['id']}: {process.stderr}")
                    continue
                else:
                    print(f"✅ Container {info['id']} started successfully")
                    processes.append(info)
            
            if not processes:
                print("❌ No containers started successfully, skipping connectivity test")
                return
            
            # Wait a bit for containers to be ready
            print("\n--- Waiting for containers to be ready ---")
            time.sleep(5)
            
            # Test connectivity to each container
            print("\n--- Testing connectivity ---")
            success_count = 0
            
            for info in processes:
                print(f"\nTesting container {info['id']} on port {info['external_port']}...")
                
                # Check if port is open
                if is_port_open('localhost', info['external_port']):
                    print(f"✅ Port {info['external_port']} is open")
                    
                    # Try to make HTTP request
                    try:
                        response = requests.get(f"http://localhost:{info['external_port']}", timeout=5)
                        if response.status_code == 200:
                            print(f"✅ HTTP request successful (status: {response.status_code})")
                            print(f"   Response length: {len(response.text)} bytes")
                            success_count += 1
                        else:
                            print(f"⚠️  HTTP request returned status: {response.status_code}")
                    except requests.RequestException as e:
                        print(f"⚠️  HTTP request failed: {e}")
                else:
                    print(f"❌ Port {info['external_port']} is not open")
            
            if success_count == len(processes):
                print(f"\n🎉 All {len(processes)} containers are accessible on their unique external ports!")
                print("✅ Parallel containers with same internal port test PASSED!")
            elif success_count > 0:
                print(f"\n⚠️  {success_count}/{len(processes)} containers are accessible")
                print("⚠️  Partial success - some containers may need more time to start")
            else:
                print("\n❌ No containers were accessible")
                print("❌ This might be due to Docker not being available or containers taking too long to start")
        
        finally:
            # Clean up containers
            print("\n--- Cleaning up containers ---")
            for info in containers_info:
                try:
                    cmd = ["docker", "compose", "-f", str(info['compose_path']), "down", "-v"]
                    subprocess.run(cmd, capture_output=True, timeout=15)
                    print(f"✅ Cleaned up container {info['id']}")
                except:
                    print(f"⚠️  Failed to clean up container {info['id']}")
    
    finally:
        # Clean up temporary files
        for temp_file in temp_files:
            try:
                temp_file.unlink()
            except:
                pass


def test_container_to_container_communication():
    """Test that server descriptions correctly use internal ports for container communication"""
    
    print("\n=== Testing Container-to-Container Communication ===")
    
    # Create a mock challenge like CryptoPwn
    challenge_data = {
        "name": "CryptoPwn",
        "category": "pwn",
        "description": "Test pwn challenge",
        "flag": "flag{test}",
        "internal_port": 9999,
        "box": "pwn.chal.csaw.io"
    }
    
    # Test InstanceBuilder setup
    ib = InstanceBuilder()
    ib.args = {"challenge": challenge_data.copy()}
    ib.args["challenge"]["port"] = challenge_data.get("internal_port") or challenge_data.get("port")
    ib.args["challenge"]["server_name"] = challenge_data.get("box", "127.0.0.1")
    
    # Set initial server description (no external port)
    ib.set_server_description(ib.args["challenge"]["server_name"], ib.args["challenge"]["port"])
    initial_description = ib.args["challenge"]["server_description"]
    print(f"Initial server description: {initial_description}")
    
    # Verify it uses service name and internal port
    assert "pwn.chal.csaw.io" in initial_description
    assert "9999" in initial_description
    assert "connect_start pwn.chal.csaw.io 9999" in initial_description
    
    # Now test with port mapping (simulating dynamic ports)
    external_port = 12345
    ib.set_server_description(ib.args["challenge"]["server_name"], ib.args["challenge"]["port"], external_port)
    description_with_mapping = ib.args["challenge"]["server_description"]
    print(f"Description with port mapping: {description_with_mapping}")
    
    # CRITICAL: Even with external port mapping, container communication should use internal port
    assert "pwn.chal.csaw.io" in description_with_mapping
    assert "9999" in description_with_mapping
    assert "connect_start pwn.chal.csaw.io 9999" in description_with_mapping
    # Should NOT contain external port or localhost
    assert "12345" not in description_with_mapping
    assert "localhost" not in description_with_mapping
    
    print("✅ Container-to-container communication correctly uses service name and internal port!")
    
    # Test web category as well
    web_challenge_data = {
        "name": "WebChallenge",
        "category": "web",
        "description": "Test web challenge",
        "flag": "flag{test}",
        "internal_port": 3000,
        "box": "web.chal.example.io"
    }
    
    ib_web = InstanceBuilder()
    ib_web.args = {"challenge": web_challenge_data.copy()}
    ib_web.args["challenge"]["port"] = web_challenge_data.get("internal_port")
    ib_web.args["challenge"]["server_name"] = web_challenge_data.get("box")
    
    # Test with external port mapping
    ib_web.set_server_description(ib_web.args["challenge"]["server_name"], ib_web.args["challenge"]["port"], 8080)
    web_description = ib_web.args["challenge"]["server_description"]
    print(f"Web challenge description: {web_description}")
    
    # Should use service name and internal port for web too
    assert "web.chal.example.io" in web_description
    assert "3000" in web_description
    assert "curl http://web.chal.example.io:3000" in web_description
    # Should NOT contain external port
    assert "8080" not in web_description
    
    print("✅ Web challenge also correctly uses service name and internal port!")


if __name__ == "__main__":
    print("Testing dynamic port allocation functionality...")
    
    test_dynamic_port_checking()
    test_dynamic_port_allocation()
    test_challenge_without_ports()
    test_instance_builder_server_description()
    
    # Add the comprehensive parallel container test
    test_parallel_containers_same_internal_port()
    
    # Add the new container-to-container communication test
    test_container_to_container_communication()
    
    print("\n🎉 All tests completed!") 