# Dynamic Port Allocation for Parallel CTF Execution

This document describes the new dynamic port allocation feature that enables running multiple CTF challenges in parallel without port conflicts.

## Problem Statement

Previously, CTF challenges using docker-compose files with fixed port mappings (e.g., `8000:8000`, `9999:9999`) could not be run in parallel because they would conflict on the same host ports. This limitation prevented efficient parallel execution of multiple CTF tasks.

## Solution Overview

The dynamic port allocation system automatically:

1. **Assigns unique external ports** for each instance (e.g., 10001, 10002, 10003 instead of 8000)
2. **Creates isolated networks** with unique names (e.g., `ctfnet-abc123`, `ctfnet-def456`)
3. **Generates temporary docker-compose files** with modified port mappings and service names
4. **Updates challenge configurations** to reflect the new port assignments
5. **Handles cleanup** of temporary files and networks

## Usage

### Basic Usage

Enable dynamic port allocation by setting the `enable_dynamic_ports` flag:

```python
from sweagent.environment.swe_env import EnvironmentArguments, SWEEnv

args = EnvironmentArguments(
    data_path="path/to/challenge.json",
    repo_path="path/to/challenge/directory", 
    enable_dynamic_ports=True,  # Enable dynamic port allocation
    verbose=True
)

env = SWEEnv(args)
print(f"Port mappings: {env.port_mappings}")  # e.g., {'8000': 10001}
print(f"Dynamic network: {env.dynamic_network_name}")  # e.g., 'ctfnet-abc123'
```

### Parallel Execution

```python
import threading
from sweagent.environment.swe_env import EnvironmentArguments, SWEEnv

def run_challenge(challenge_path, instance_id):
    args = EnvironmentArguments(
        data_path=challenge_path,
        enable_dynamic_ports=True,
        verbose=True
    )
    
    env = SWEEnv(args)
    try:
        # Your challenge solving logic here
        print(f"Instance {instance_id} using ports: {env.port_mappings}")
        # ... solve challenge ...
    finally:
        env.close()

# Run multiple challenges in parallel
challenges = [
    "path/to/challenge1/challenge.json",
    "path/to/challenge2/challenge.json", 
    "path/to/challenge3/challenge.json"
]

threads = []
for i, challenge in enumerate(challenges):
    thread = threading.Thread(target=run_challenge, args=(challenge, i))
    threads.append(thread)
    thread.start()

for thread in threads:
    thread.join()
```

## How It Works

### 1. Port Discovery and Allocation

When `enable_dynamic_ports=True`, the system:

- Parses the original docker-compose.yml file
- Identifies all port mappings (e.g., `8000:80`, `9999:9999`)
- Allocates available ports in the range 10000-20000 for each internal port
- Creates a mapping dictionary (e.g., `{'80': 10001, '9999': 10002}`)

### 2. Docker Compose Modification

The system creates a temporary docker-compose file with:

- **Unique service names**: `service-name` → `service-name-abc123`
- **Dynamic port mappings**: `8000:80` → `10001:80`
- **Isolated networks**: `ctfnet` → `ctfnet-abc123`

Example transformation:

**Original docker-compose.yml:**
```yaml
services:
  web-server:
    image: nginx:latest
    ports:
      - "8000:80"
    networks:
      ctfnet:
        aliases:
          - web.chal.example.com

networks:
  ctfnet:
    external: true
```

**Generated docker-compose-abc123.yml:**
```yaml
services:
  web-server-abc123:
    image: nginx:latest
    ports:
      - "10001:80"
    networks:
      ctfnet-abc123:
        aliases:
          - web.chal.example.com

networks:
  ctfnet-abc123:
    driver: bridge
    name: ctfnet-abc123
```

### 3. Network Isolation

Each instance gets its own Docker network:
- SWE-agent container connects to `ctfnet-abc123`
- Challenge containers run in the same isolated network
- No cross-instance network interference

### 4. Challenge Configuration Updates

The system automatically updates challenge configurations:
- Updates `challenge["port"]` to reflect the new external port
- Modifies server descriptions for agent instructions
- Maintains compatibility with existing challenge formats

## Configuration Options

### EnvironmentArguments

```python
@dataclass
class EnvironmentArguments:
    # ... existing fields ...
    enable_dynamic_ports: bool = False  # Enable dynamic port allocation
```

### Port Range Configuration

The default port range is 10000-20000. You can modify this in `sweagent/environment/utils.py`:

```python
DEFAULT_PORT_RANGE_START = 10000
DEFAULT_PORT_RANGE_END = 20000
```

## Compatibility

### Backward Compatibility

- **Default behavior unchanged**: `enable_dynamic_ports=False` by default
- **Existing challenges work**: No modifications needed to existing docker-compose files
- **API compatibility**: All existing APIs remain unchanged

### Supported Docker Compose Features

- ✅ Port mappings (`ports:`)
- ✅ Networks (`networks:`)
- ✅ Service aliases
- ✅ External networks (converted to internal)
- ✅ Multiple services per compose file

### Limitations

- **Port range**: Limited to 10000 available ports (10000-20000)
- **Docker compose v3+**: Requires modern docker-compose format
- **Network isolation**: Services in different instances cannot communicate

## Troubleshooting

### Common Issues

1. **Port exhaustion**: If you need more than 10000 parallel instances, increase the port range
2. **Permission errors**: Ensure Docker daemon is running and accessible
3. **Network conflicts**: Check for existing networks with similar names

### Debug Information

Enable verbose logging to see detailed port allocation:

```python
args = EnvironmentArguments(
    # ... other args ...
    enable_dynamic_ports=True,
    verbose=True  # Enable detailed logging
)
```

Look for log messages like:
```
🔌 Dynamic port mappings: {'8000': 10001, '9999': 10002}
🌱 Created dynamic docker-compose at /tmp/docker-compose-abc123.yml
```

### Manual Cleanup

If automatic cleanup fails, you can manually remove:

```bash
# Remove temporary compose files
rm /tmp/docker-compose-*

# Remove dynamic networks
docker network ls | grep ctfnet- | awk '{print $1}' | xargs docker network rm

# Remove dynamic containers
docker ps -a | grep -- "-[a-f0-9]\{10\}" | awk '{print $1}' | xargs docker rm -f
```

## Performance Considerations

### Resource Usage

- **Memory**: Each instance requires additional Docker containers
- **Ports**: Uses one port per exposed service per instance
- **Networks**: Creates one Docker network per instance
- **Disk**: Temporary docker-compose files (minimal overhead)

### Scaling Recommendations

- **Small scale** (1-10 instances): No special considerations
- **Medium scale** (10-100 instances): Monitor port usage and Docker daemon limits
- **Large scale** (100+ instances): Consider container orchestration platforms

## Examples

### Example 1: Web Challenge

```python
# Web challenge with HTTP service on port 80
args = EnvironmentArguments(
    data_path="web_challenge/challenge.json",
    enable_dynamic_ports=True
)

env = SWEEnv(args)
# Access web service at localhost:{env.port_mappings['80']}
```

### Example 2: PWN Challenge

```python
# PWN challenge with netcat service on port 9999
args = EnvironmentArguments(
    data_path="pwn_challenge/challenge.json", 
    enable_dynamic_ports=True
)

env = SWEEnv(args)
# Connect to service: nc localhost {env.port_mappings['9999']}
```

### Example 3: Multi-Service Challenge

```python
# Challenge with multiple services (web + admin)
args = EnvironmentArguments(
    data_path="complex_challenge/challenge.json",
    enable_dynamic_ports=True
)

env = SWEEnv(args)
# Web service: localhost:{env.port_mappings['80']}
# Admin service: localhost:{env.port_mappings['8080']}
```

## Implementation Details

### Key Files Modified

1. **`sweagent/environment/utils.py`**:
   - `get_available_port()`: Port allocation logic
   - `create_dynamic_docker_compose()`: Docker compose modification
   - `get_docker_compose()`: Updated to support dynamic ports
   - `attach_network_interface_to_container()`: Network management

2. **`sweagent/environment/swe_env.py`**:
   - `EnvironmentArguments`: Added `enable_dynamic_ports` flag
   - `SWEEnv`: Added port mapping and network tracking
   - `_init_docker_compose()`: Dynamic port allocation logic
   - `_init_docker_network()`: Dynamic network connection
   - `close()`: Cleanup of temporary files

### Testing

Run the test script to verify functionality:

```bash
python test_dynamic_ports.py
```

This will demonstrate both dynamic and static port allocation modes. 