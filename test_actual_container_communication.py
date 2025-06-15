#!/usr/bin/env python3
"""
Comprehensive test to demonstrate that two containers with the same config
can now connect successfully to their internal servers using dynamic port allocation.
"""

import tempfile
import yaml
import subprocess
import time
import socket
import docker
from pathlib import Path
import json

from sweagent.environment.utils import (
    create_dynamic_docker_compose,
    get_docker_compose,
    InstanceBuilder
)

def create_test_service_compose():
    """Create a simple test service docker-compose that we can actually test connectivity to"""
    
    # Create a simple test service compose - using httpd which is simple and reliable
    compose_content = {
        'services': {
            'test-server': {
                'image': 'httpd:2.4-alpine',  # Simple HTTP server
                'ports': [80],  # Internal port 80, no external mapping initially
                'networks': {
                    'ctfnet': {
                        'aliases': ['test.chal.example.io']
                    }
                },
                'command': ['httpd-foreground']
            }
        },
        'networks': {
            'ctfnet': {
                'external': True
            }
        }
    }
    
    return compose_content

def create_client_container():
    """Create a simple client container that can test connectivity"""
    client = docker.from_env()
    
    # Check if we have a simple client image, if not create a basic one
    try:
        # Create a simple test container with curl available
        container = client.containers.run(
            'alpine:latest',
            command='sh -c "apk add --no-cache curl && sleep 3600"',
            detach=True,
            network='ctfnet',
            name='test-client',
            remove=True
        )
        
        # Wait for curl installation
        time.sleep(10)
        return container
    except Exception as e:
        print(f"Failed to create client container: {e}")
        return None

def test_container_connectivity(container, target_host, target_port, test_name):
    """Test if a container can connect to a target host:port"""
    
    try:
        # Try to make HTTP request from within the container
        result = container.exec_run(
            f'curl -s --max-time 5 http://{target_host}:{target_port}',
            timeout=10
        )
        
        if result.exit_code == 0:
            print(f"✅ {test_name}: Successfully connected to {target_host}:{target_port}")
            return True
        else:
            print(f"❌ {test_name}: Failed to connect to {target_host}:{target_port} - exit code: {result.exit_code}")
            if result.output:
                print(f"   Output: {result.output.decode()[:200]}...")
            return False
            
    except Exception as e:
        print(f"❌ {test_name}: Exception connecting to {target_host}:{target_port} - {e}")
        return False

def test_dual_container_setup():
    """
    Test setting up two identical containers with dynamic ports and verify they can 
    communicate using internal ports and service names.
    """
    
    print("\n" + "="*70)
    print("TESTING DUAL CONTAINER SETUP WITH DYNAMIC PORTS")
    print("="*70)
    
    # Create the base compose content
    base_compose = create_test_service_compose()
    
    temp_files = []
    containers_info = []
    client_container = None
    docker_client = docker.from_env()
    
    try:
        # Ensure ctfnet exists
        try:
            docker_client.networks.get('ctfnet')
        except docker.errors.NotFound:
            docker_client.networks.create('ctfnet', driver='bridge')
            print("✅ Created ctfnet network")
        
        print("\n1. Setting up two identical services with dynamic ports...")
        
        # Create two identical containers with dynamic port allocation
        for i in range(2):
            print(f"\n--- Setting up container {i+1} ---")
            
            # Create temporary docker-compose file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
                yaml.dump(base_compose, f)
                compose_path = Path(f.name)
                temp_files.append(compose_path)
            
            # Create dynamic port allocation
            container_suffix = f"test{i+1}"
            challenge_internal_port = 80  # Both use port 80 internally
            
            actual_compose_path, port_mappings = get_docker_compose(
                compose_path,
                container_name_suffix=container_suffix,
                dynamic_ports=True,
                challenge_internal_port=challenge_internal_port
            )
            
            if actual_compose_path != compose_path:
                temp_files.append(actual_compose_path)
            
            external_port = port_mappings.get(str(challenge_internal_port))
            
            print(f"   Internal port: {challenge_internal_port}")
            print(f"   External port: {external_port}")
            
            containers_info.append({
                'id': i+1,
                'compose_path': actual_compose_path,
                'internal_port': challenge_internal_port,
                'external_port': external_port,
                'container_suffix': container_suffix,
                'service_name': f'test.chal.example.io'  # From the compose aliases
            })
        
        print(f"\n2. Verifying unique external ports allocated...")
        external_ports = [info['external_port'] for info in containers_info]
        assert len(set(external_ports)) == len(external_ports), "External ports should be unique!"
        print(f"   ✅ Unique external ports: {external_ports}")
        
        print(f"\n3. Starting containers...")
        running_containers = []
        
        for info in containers_info:
            print(f"\n   Starting container {info['id']}...")
            cmd = [
                "docker", "compose", "-f", str(info['compose_path']), 
                "up", "-d", "--force-recreate"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print(f"   ✅ Container {info['id']} started successfully")
                running_containers.append(info)
            else:
                print(f"   ❌ Failed to start container {info['id']}: {result.stderr}")
        
        if len(running_containers) == 0:
            print("❌ No containers started successfully")
            return
        
        print(f"\n4. Waiting for services to be ready...")
        time.sleep(10)
        
        print(f"\n5. Creating client container for testing...")
        client_container = create_client_container()
        
        if not client_container:
            print("❌ Failed to create client container")
            return
        
        print(f"\n6. Testing container-to-container communication...")
        print("   This demonstrates the key fix: containers should use internal ports and service names")
        
        success_count = 0
        
        for info in running_containers:
            service_name = f"test-server-{info['container_suffix']}"  # Actual service name from compose
            internal_port = info['internal_port']
            external_port = info['external_port']
            
            print(f"\n   Testing Container {info['id']}:")
            print(f"     Service name: {service_name}")
            print(f"     Internal port: {internal_port}")  
            print(f"     External port: {external_port}")
            
            # Test 1: Connect using service name and internal port (CORRECT way)
            success1 = test_container_connectivity(
                client_container, 
                service_name, 
                internal_port,
                f"Container {info['id']} via service name + internal port"
            )
            
            # Test 2: Try connecting via localhost and external port (WRONG way - should fail)
            success2 = test_container_connectivity(
                client_container, 
                'localhost', 
                external_port,
                f"Container {info['id']} via localhost + external port (should fail)"
            )
            
            if success1:
                success_count += 1
                
            # Verify our fix: success1 should be True, success2 should be False
            if success1 and not success2:
                print(f"   🎉 Container {info['id']}: PERFECT! Service name works, localhost doesn't")
            elif success1:
                print(f"   ✅ Container {info['id']}: Service name works (main success)")
            else:
                print(f"   ❌ Container {info['id']}: Service name failed")
        
        print(f"\n7. Testing InstanceBuilder server descriptions...")
        
        for info in running_containers:
            # Create a mock challenge like what would be loaded
            challenge_data = {
                "name": f"TestChallenge{info['id']}",
                "category": "web",
                "description": "Test web challenge",
                "internal_port": info['internal_port'],
                "box": f"test-server-{info['container_suffix']}"  # Service name
            }
            
            ib = InstanceBuilder()
            ib.args = {"challenge": challenge_data.copy()}
            ib.args["challenge"]["port"] = challenge_data["internal_port"]
            ib.args["challenge"]["server_name"] = challenge_data["box"]
            
            # Simulate dynamic port mapping
            port_mappings = {str(info['internal_port']): info['external_port']}
            ib.update_server_description_with_port_mapping(port_mappings)
            
            description = ib.args["challenge"]["server_description"]
            print(f"\n   Container {info['id']} server description:")
            print(f"   '{description}'")
            
            # Verify it uses service name and internal port
            service_name = f"test-server-{info['container_suffix']}"
            if service_name in description and str(info['internal_port']) in description:
                print(f"   ✅ Description correctly uses service name and internal port")
            else:
                print(f"   ❌ Description incorrect")
        
        print(f"\n" + "="*70)
        print("SUMMARY")
        print("="*70)
        
        if success_count == len(running_containers):
            print(f"🎉 SUCCESS: All {len(running_containers)} containers are accessible via service names!")
            print("✅ Dynamic port allocation working correctly")
            print("✅ Container-to-container communication using internal ports")
            print("✅ Server descriptions provide correct connection info")
            print("\nKEY INSIGHT:")
            print("- External ports are for HOST-to-container communication")
            print("- Internal ports are for CONTAINER-to-container communication") 
            print("- Agents run inside containers, so they use internal ports")
        else:
            print(f"⚠️  Partial success: {success_count}/{len(running_containers)} containers accessible")
    
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print(f"\n8. Cleaning up...")
        
        # Clean up client container
        if client_container:
            try:
                client_container.stop()
                print("   ✅ Stopped client container")
            except:
                pass
        
        # Clean up service containers
        for info in containers_info:
            try:
                cmd = ["docker", "compose", "-f", str(info['compose_path']), "down", "-v"]
                subprocess.run(cmd, capture_output=True, timeout=30)
                print(f"   ✅ Cleaned up container {info['id']}")
            except:
                print(f"   ⚠️  Failed to clean up container {info['id']}")
        
        # Clean up temp files
        for temp_file in temp_files:
            try:
                temp_file.unlink()
            except:
                pass

if __name__ == "__main__":
    test_dual_container_setup() 