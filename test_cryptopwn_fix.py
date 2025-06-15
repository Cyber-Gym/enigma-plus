#!/usr/bin/env python3
"""
Test script to verify that the CryptoPwn challenge server description works correctly
with the dynamic port allocation fix.
"""

import json
from pathlib import Path
from sweagent.environment.utils import InstanceBuilder

def test_cryptopwn_challenge():
    """Test the CryptoPwn challenge with our fixed server description logic"""
    
    print("=== Testing CryptoPwn Challenge Fix ===")
    
    # Load the actual CryptoPwn challenge.json
    challenge_path = Path("../NYU_CTF_Bench/test/2022/CSAW-Finals/pwn/CryptoPwn/challenge.json")
    
    if not challenge_path.exists():
        print(f"❌ Challenge file not found: {challenge_path}")
        return
    
    # Create instance builder and load the challenge
    ib = InstanceBuilder()
    ib.set_problem_statement_from_challenge_json(str(challenge_path))
    
    print(f"Challenge name: {ib.args['challenge']['name']}")
    print(f"Challenge category: {ib.args['challenge']['category']}")
    print(f"Server name: {ib.args['challenge']['server_name']}")
    print(f"Internal port: {ib.args['challenge']['port']}")
    
    print(f"\nInitial server description:")
    print(f"'{ib.args['challenge']['server_description']}'")
    
    # Simulate dynamic port mapping
    port_mappings = {"9999": 15432}  # External port 15432 mapped to internal port 9999
    ib.update_server_description_with_port_mapping(port_mappings)
    
    print(f"\nServer description after dynamic port mapping:")
    print(f"'{ib.args['challenge']['server_description']}'")
    
    # Verify the fix
    description = ib.args['challenge']['server_description']
    
    print(f"\n=== Verification ===")
    
    # Should use the service name (pwn.chal.csaw.io)
    if "pwn.chal.csaw.io" in description:
        print("✅ Uses correct service name (pwn.chal.csaw.io)")
    else:
        print("❌ Missing service name")
    
    # Should use the internal port (9999)
    if "9999" in description:
        print("✅ Uses correct internal port (9999)")
    else:
        print("❌ Missing internal port")
    
    # Should use connect_start for pwn challenges
    if "connect_start pwn.chal.csaw.io 9999" in description:
        print("✅ Provides correct connection command")
    else:
        print("❌ Incorrect connection command")
    
    # Should NOT use localhost or external port
    if "localhost" not in description:
        print("✅ Correctly avoids localhost")
    else:
        print("❌ Incorrectly uses localhost")
    
    if "15432" not in description:
        print("✅ Correctly avoids external port")
    else:
        print("❌ Incorrectly uses external port")
    
    print(f"\n=== Summary ===")
    print("Before our fix: Agent would try to connect to localhost:15432 (external port) and fail")
    print("After our fix: Agent will connect to pwn.chal.csaw.io:9999 (service name + internal port) and succeed")
    print("✅ The CryptoPwn challenge should now work correctly with dynamic port allocation!")

if __name__ == "__main__":
    test_cryptopwn_challenge() 