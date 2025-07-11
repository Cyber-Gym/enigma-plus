# Network Restrictions in SWE-agent

## Overview

SWE-agent now includes optional network restrictions to prevent external connections while maintaining functionality for local development and package management. This feature is designed to:

1. **Allow setup phase package downloads** (pip install during environment initialization)
2. **Allow localhost connections** (127.0.0.1) for local services  
3. **Allow Docker internal networks** for CTF challenges and container communication
4. **Block external IP connections** after setup to prevent data exfiltration and unauthorized access

## CRITICAL SECURITY FIX: Challenge Container Restrictions

**IMPORTANT**: Previous versions only applied network restrictions to the SWE-agent container, but **challenge containers created by docker-compose were unrestricted!** 

This has been fixed. Network restrictions are now applied to **ALL containers**:

- ✅ **SWE-agent container** (e.g., `parallel-1-ca-0ctf2017-pwn-babyheap-try1`)
- ✅ **Challenge containers** (e.g., `babyheap-1-ca-0ctf2017-pwn-babyheap-try1`)

This prevents agents from accessing external networks through any container in the environment.

## Container Architecture

For CTF challenges, SWE-agent creates multiple containers:

```
┌─────────────────────────────────────────────────────────────┐
│ SWE-agent Container (parallel-1-ca-0ctf2017-pwn-babyheap-try1) │
│ - Runs the agent code                                       │
│ - Has network restrictions applied ✅                       │
│ - Connected to CTF network                                  │
└─────────────────────────────────────────────────────────────┘
               │
               │ Docker network
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Challenge Container (babyheap-1-ca-0ctf2017-pwn-babyheap-try1) │
│ - Runs the CTF challenge service                            │
│ - NOW has network restrictions applied ✅ (FIXED)          │
│ - Connected to CTF network                                  │
└─────────────────────────────────────────────────────────────┘
```

Both containers can communicate with each other via Docker internal networks, but **neither can access external internet**.

## Important: Setup Phase vs Runtime Phase

**NEW**: Network restrictions are now applied **after** the environment setup phase to resolve compatibility issues:

- **Setup Phase**: Full internet access for package downloads (pip install flake8, etc.)
- **Runtime Phase**: Strict network restrictions applied after setup is complete
- **Agent Execution**: External access blocked, only localhost and Docker networks allowed

This ensures that required packages can be installed during setup while still protecting against external access during agent execution.

## Configuration

Network restrictions are controlled by the `enable_network_restrictions` parameter in `EnvironmentArguments`:

```python
from sweagent.environment.swe_env import EnvironmentArguments

# Enable network restrictions (default)
args = EnvironmentArguments(
    data_path="path/to/data",
    enable_network_restrictions=True  # This is the default
)

# Disable network restrictions
args = EnvironmentArguments(
    data_path="path/to/data", 
    enable_network_restrictions=False
)
```

## Command Line Usage

When using the command line interface, you can control network restrictions with the `--enable-network-restrictions` flag:

```bash
# Enable network restrictions (default behavior)
python -m sweagent.agent.agents --enable-network-restrictions

# Disable network restrictions
python -m sweagent.agent.agents --no-enable-network-restrictions
```

## What is Allowed

With network restrictions enabled, the following connections are permitted:

### ✅ Allowed Connections

**During Setup Phase (before restrictions applied):**
- **All external connections**: Required for pip install, apt update, etc.
- **Package repositories**: PyPI, apt repositories, etc.

**During Runtime Phase (after restrictions applied):**
- **Localhost (127.0.0.0/8)**: All connections to localhost
- **Private networks**: Docker internal networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- **Container-to-container**: CTF challenge containers can communicate with SWE-agent
- **Established connections**: Response traffic for outgoing connections

### ❌ Blocked Connections (Runtime Phase Only)

- **External HTTP/HTTPS**: Prevents data exfiltration to external servers
- **External SSH (port 22)**: Prevents unauthorized SSH connections
- **External Telnet (port 23)**: Blocks telnet connections
- **External FTP (port 21)**: Prevents FTP connections
- **External database ports**: PostgreSQL (5432), MySQL (3306), etc.
- **External RDP (port 3389)**: Blocks remote desktop connections
- **Any other external ports**: General port scanning prevention

## Technical Implementation

The network restrictions are implemented using iptables rules within **ALL** Docker containers:

### SWE-agent Container
```bash
# Applied after environment setup in reset() method
iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT     # localhost
iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT   # Docker networks
iptables -A OUTPUT -j REJECT                     # Block everything else
```

### Challenge Containers  
```bash
# Applied after docker-compose startup in _init_docker_compose()
iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT     # localhost
iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT   # Docker networks
iptables -A OUTPUT -j REJECT                     # Block everything else
```

**Key Changes**: Network restrictions are applied **after** the environment setup is complete, including:
- pip install flake8 (linting)
- apt install build-essential
- conda environment setup
- Custom environment setup scripts
- **docker-compose service startup** (NEW)

## Testing Network Restrictions

A comprehensive test script is provided to verify that network restrictions work on all containers:

```bash
# Run the comprehensive network restrictions test
python test_challenge_container_restrictions.py
```

The test script verifies:
- ✅ SWE-agent container: External connections blocked
- ✅ Challenge containers: External connections blocked  
- ✅ Container-to-container communication works
- ✅ Both cached and non-cached scenarios work

## Timing and Lifecycle

1. **Container Creation**: Containers start with full network access
2. **Environment Setup**: Install packages, setup environments (unrestricted)
3. **Docker-compose Setup**: Start challenge containers (unrestricted)
4. **Apply Restrictions**: Network restrictions applied to ALL containers
5. **Verification**: Test that restrictions work on all containers
6. **Agent Execution**: Agent runs with network restrictions in place

## Requirements

Network restrictions require:
- Docker containers to run in **privileged mode** (for iptables access)
- The `iptables` package in containers (automatically installed if missing)
- **Challenge containers must support iptables** (most Linux containers do)

## Performance Impact

Network restrictions have minimal performance impact:
- Slight startup delay (5-10 seconds) for iptables configuration after setup
- No runtime performance impact on allowed connections
- Blocked connections fail quickly with ICMP rejection

## Troubleshooting

### Challenge containers have external access
**FIXED**: This critical security issue has been resolved. If you still see external access:
1. Update to the latest version with the security fix
2. Run the test script to verify: `python test_challenge_container_restrictions.py`
3. Check logs for "Applying network restrictions to challenge containers"

### flake8 installation failing
**FIXED**: This issue has been resolved. Network restrictions are now applied after flake8 installation.

### Package downloads failing during setup
1. Check if restrictions are being applied too early (should see setup messages first)
2. Verify internet connectivity on the host system
3. Check for firewall rules blocking container access

### Network restrictions not working
1. Check if containers are running in privileged mode
2. Verify iptables is available in the containers
3. Check container logs for restriction setup errors
4. Run the comprehensive test script

### Container-to-container communication not working
1. Verify containers are on the same Docker network
2. Check that Docker internal networks are allowed in iptables rules
3. Test connectivity: `docker exec container1 ping container2`

## Security Considerations

Network restrictions provide defense-in-depth but should not be the only security measure:

- **Not a replacement for proper sandboxing**
- **Container escape could bypass restrictions**
- **Privileged mode required for iptables access**
- **Setup phase has full network access**

For maximum security, combine with:
- Container runtime security (gVisor, Kata containers)
- Network isolation at the host level
- Resource limits and monitoring
- Regular security updates

## Examples

### Basic usage with restrictions (default)
```python
from sweagent.environment.swe_env import EnvironmentArguments, SWEEnv

args = EnvironmentArguments(
    data_path="github_issue_url_here",
    enable_network_restrictions=True
)

env = SWEEnv(args)
# ALL containers will have network restrictions applied after setup
```

### CTF challenge with network restrictions
```python
from sweagent.environment.swe_env import EnvironmentArguments, SWEEnv

args = EnvironmentArguments(
    data_path="path/to/challenge.json",  # CTF challenge
    enable_network_restrictions=True,
    enable_dynamic_ports=True
)

env = SWEEnv(args)
# Both SWE-agent AND challenge containers will be restricted
```

### Disabling restrictions for debugging
```python
from sweagent.environment.swe_env import EnvironmentArguments, SWEEnv

args = EnvironmentArguments(
    data_path="github_issue_url_here", 
    enable_network_restrictions=False
)

env = SWEEnv(args)
# NO containers will have network restrictions
```

### Testing if restrictions are active
```python
# Test SWE-agent container
result = env.communicate("timeout 5 curl -I http://google.com 2>&1 || echo 'BLOCKED'")
print("SWE-agent restricted:" if "BLOCKED" in result else "SWE-agent not restricted")

# Test challenge containers (requires docker client)
import docker
client = docker.from_env()
for container in client.containers.list():
    if "challenge" in container.name:
        result = container.exec_run("timeout 5 curl -I http://google.com 2>&1 || echo 'BLOCKED'")
        output = result.output.decode()
        print(f"Challenge container {container.name} restricted:" if "BLOCKED" in output else f"Challenge container {container.name} not restricted")
```

## Version History

- **v1.0**: Initial network restrictions (SWE-agent container only)
- **v1.1**: SECURITY FIX - Network restrictions now applied to ALL containers including challenge containers
- **v1.2**: Improved timing to apply restrictions after environment setup 