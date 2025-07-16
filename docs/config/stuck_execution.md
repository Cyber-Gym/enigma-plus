# Handling Stuck Execution Issues

SWE-agent includes comprehensive timeout handling to prevent hung executions, but some scenarios may still cause timeouts. This guide explains how to diagnose and resolve stuck execution issues.

## How Timeout Constants Work

SWE-agent uses several timeout constants that are properly applied throughout the codebase:

### DOCKER_EXEC_TIMEOUT Usage
The `DOCKER_EXEC_TIMEOUT` constant is actively used in critical Docker operations:

```python
# Example from _safe_exec_run method in swe_env.py
def _safe_exec_run(self, command: str, timeout_duration: int | None = None, **kwargs) -> str:
    if timeout_duration is None:
        timeout_duration = DOCKER_EXEC_TIMEOUT  # Uses the configured timeout
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(lambda: self.container_obj.exec_run(command, **kwargs))
        result = future.result(timeout=timeout_duration)  # Applies timeout
```

### Active Timeout Protection
All critical Docker operations now use timeout protection:

- `get_pids()` - Process listing with timeout
- `interrupt()` - Process killing with timeout  
- `_validate_container_health()` - Health checks with timeout
- State retrieval operations (like `pwd`) with timeout

### Verifying Timeout Configuration

You can verify that timeout constants are properly applied by checking the logs:

```bash
# Enable verbose logging to see timeout messages
export SWE_AGENT_LOG_STREAM_LEVEL=DEBUG

# Set a short timeout for testing
export SWE_AGENT_DOCKER_EXEC_TIMEOUT=5

# Run SWE-agent and look for timeout-related log messages
python run.py --config config.yaml --verbose
```

When timeouts are working correctly, you'll see messages like:
```
DEBUG: Docker exec_run timeout set to 5.0 seconds
DEBUG: Command completed within timeout: ps -eo pid,comm,ppid --no-headers
WARNING: Docker exec_run timed out after 5s: long_running_command
```

### Testing Timeout Behavior

To test that timeouts are working:

```python
# In a Python environment with SWE-agent
import os
os.environ["SWE_AGENT_DOCKER_EXEC_TIMEOUT"] = "2"  # Very short timeout

from sweagent.environment.swe_env import SWEEnv, EnvironmentArguments

# Create environment with short timeout
args = EnvironmentArguments(data_path="your_data_path")
env = SWEEnv(args)

# This should timeout quickly for long operations:
try:
    result = env._safe_exec_run("sleep 10")  # Will timeout after 2 seconds
except RuntimeError as e:
    print(f"Expected timeout: {e}")  # Should show timeout message
```

## Common Stuck Execution Scenarios

### 1. Long-Running Filesystem Operations
Commands like `grep -r`, `find /`, or `locate` can take excessive time:

```bash
# Instead of this (may hang):
grep -r "pattern" /

# Use this:
timeout 30 grep -r "pattern" /specific/directory
find /specific/directory -name "*.py" -exec grep -l "pattern" {} \;
```

### 2. Interactive Programs Waiting for Input
Programs that expect user input will hang:

```bash
# Instead of this (will hang):
python script.py

# Use this:
python script.py < /dev/null
echo "y" | python script.py
timeout 10 python script.py
```

### 3. Network Operations That Hang
Downloads, git operations, or API calls can hang:

```bash
# Instead of this (may hang):
curl https://example.com/large-file

# Use this:
timeout 30 curl --connect-timeout 5 --max-time 30 https://example.com/large-file
```

## Environment Variables for Timeout Configuration

You can customize timeout behavior using these environment variables:

```bash
# Agent action timeouts
export SWE_AGENT_ACTION_TIMEOUT=60              # Max time for any command (default: 25s)
export SWE_AGENT_ACTION_NO_OUTPUT_TIMEOUT=30    # Time to wait with no output (default: same as above)

# Docker operation timeouts
export SWE_AGENT_DOCKER_EXEC_TIMEOUT=45         # Docker exec timeout (default: 30s)
export SWE_AGENT_CONTAINER_HEALTH_CHECK_TIMEOUT=10  # Health check timeout (default: 5s)

# Recovery mechanisms
export SWE_AGENT_INTERRUPT_TIMEOUT=30           # Process interrupt timeout (default: 20s)
export SWE_AGENT_MAX_EXECUTION_RETRIES=3        # Max retry attempts (default: 2)
```

## Troubleshooting Stuck Executions

### 1. Check for High Process Count
If you see "HIGH PROCESS COUNT" messages:

```bash
# Clean up stuck processes
pkill -f "stuck_process_name"
ps aux | grep python | awk '{print $2}' | xargs kill -9
```

### 2. Container Unresponsive
If the container becomes unresponsive:

- The environment will automatically restart the container
- Check Docker logs: `docker logs <container_name>`
- Consider using a fresh container instead of persistent containers

### 3. Long Operations Detection
When you see "LONG OPERATION DETECTED":

- Use more specific search paths instead of searching entire filesystem
- Add progress indicators to your scripts
- Break large operations into smaller chunks

### 4. Network Restrictions
If network operations hang with restrictions enabled:

- Ensure you're only accessing allowed hosts (localhost, Docker networks)
- Check if the operation requires external internet access (blocked by restrictions)

## Best Practices

### 1. Use Timeouts in Commands
Always wrap potentially long-running commands:

```bash
# Good practices:
timeout 30 grep -r "pattern" specific_directory/
timeout 10 python -c "import requests; print(requests.get('http://localhost:8080').text)"
find . -name "*.py" -maxdepth 3  # Limit search depth
```

### 2. Add Progress Indicators
For long operations, add progress output:

```python
# Instead of silent processing:
for i in range(1000):
    process_item(i)

# Use this:
for i in range(1000):
    if i % 100 == 0:
        print(f"Progress: {i}/1000")
    process_item(i)
```

### 3. Use Non-Interactive Flags
Always use non-interactive flags for tools:

```bash
# Good practices:
apt-get install -y package
pip install --no-input package  
git clone --quiet url
```

### 4. Monitor Resource Usage
Before running resource-intensive operations:

```bash
# Check available resources
df -h      # Disk space
free -h    # Memory
ps aux     # Running processes
```

## Configuration Examples

### For Complex Codebases
```bash
export SWE_AGENT_ACTION_TIMEOUT=120
export SWE_AGENT_ACTION_NO_OUTPUT_TIMEOUT=60
export SWE_AGENT_MAX_EXECUTION_RETRIES=3
```

### For Quick Testing
```bash
export SWE_AGENT_ACTION_TIMEOUT=15
export SWE_AGENT_ACTION_NO_OUTPUT_TIMEOUT=10
export SWE_AGENT_MAX_EXECUTION_RETRIES=1
```

### For Network-Heavy Tasks
```bash
export SWE_AGENT_ACTION_TIMEOUT=180
export SWE_AGENT_DOCKER_EXEC_TIMEOUT=60
export SWE_AGENT_INTERRUPT_TIMEOUT=45
```

## Getting Help

If you continue to experience stuck execution issues:

1. Check the SWE-agent logs for specific error messages
2. Review the Docker container logs
3. Try running with increased verbosity: `--verbose`
4. Consider using a fresh container instead of persistent containers
5. Report the issue with logs and reproduction steps on GitHub

The SWE-agent environment is designed to automatically detect and handle most stuck execution scenarios, but proper command usage and timeout configuration can prevent most issues from occurring. 