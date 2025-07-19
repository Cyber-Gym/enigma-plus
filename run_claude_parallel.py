#!/usr/bin/env python3
"""
Parallel CTF Challenge Runner

This script runs CTF challenges in parallel using tmux sessions and Docker containers.
It's a Python conversion of the original bash script with improved error handling and configuration.

All configuration is now handled through YAML files. The script accepts an optional config file path.

Usage:
    python run_claude_parallel.py [--config CONFIG_FILE]

Examples:
    python run_claude_parallel.py                                    # Use default config file
    python run_claude_parallel.py --config my_config.yaml          # Use custom config file
    python run_claude_parallel.py -c /path/to/config.yaml          # Use config file in different location

Environment Variables:
    The script requires different environment variables based on the model type:
    
    For AWS model type (model.type: "aws"):
        export ISENGARD_PRODUCTION_ACCOUNT=true
        export AWS_ACCESS_KEY_ID=your_access_key
        export AWS_SECRET_ACCESS_KEY=your_secret_key
        export AWS_SESSION_TOKEN=your_session_token
    
    For OpenAI model type (model.type: "openai"):
        export OPENAI_API_KEY=your_api_key
        export OPENAI_API_BASE_URL=your_api_base_url

Configuration:
    The script looks for a YAML configuration file (default: parallel_runner_config.yaml) that contains:
    
    dataset:
      name: "ctf_dataset"                    # Dataset name (without .json extension)
      start_index: 1                         # Starting challenge index (1-based, optional)
      end_index: 10                          # Ending challenge index (1-based, optional)
      writeup_mapping_file: "path/to/task_writeup_mapping.json"  # Optional writeup file
    
    execution:
      try_times: 1                           # Number of times to try each challenge
      start_try: 1                           # Starting try number (default: 1, must be <= try_times)
      parallel_tasks: 25                     # Number of parallel tasks
      disable_cleanup: false                 # Disable final cleanup
      disable_initial_cleanup: false         # Disable initial cleanup
      enable_logs: false                     # Enable log file creation
      auto_cleanup_logs: true                # Auto-cleanup logs on success
      enable_per_task_cleanup: true          # Enable per-task Docker cleanup (prevents resource exhaustion)
      max_wait_time: 3600                    # Maximum wait time in seconds
      delay_between_submissions: 2           # Delay between submissions
    
    model:
      type: "aws"                            # Model provider: "aws" or "openai"
      name: "bedrock:us.anthropic.claude-3-5-sonnet-20241022-v2:0"
      temperature: 0.0                       # Model temperature (0.0 = deterministic, higher = more random)
      top_p: 0.95                            # Top-p for nucleus sampling (0.0 to 1.0)
    
    docker:
      image_name: "sweagent/enigma:latest"
      per_instance_step_limit: 40
    
    environment:
      host_url: "http://localhost:8000"
      openai_api_key: "dummy"                # Only used if model.type is "openai"
      openai_api_base_url: "http://localhost:30000/v1"  # Only used if model.type is "openai"
      swe_agent_action_timeout: 20
    
    swe_agent:
      config_file: "config/default_ctf.yaml"
"""

# CRITICAL FIX: Suppress Modal deprecation warnings that cause script to exit
# These must be set before any imports that might trigger Modal warnings
import os
os.environ['PYTHONWARNINGS'] = 'ignore::DeprecationWarning'
os.environ['MODAL_SUPPRESS_DEPRECATION_WARNINGS'] = '1'

import argparse
import glob
import json
import logging
import random
import signal
import subprocess
import sys
import tempfile
import time
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import uuid
from datetime import datetime
import threading

import docker
import tmuxp
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('parallel_runner.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class RunnerConfig:
    """Configuration for the parallel runner"""
    dataset_name: str = "ctf_dataset"  # Default dataset name
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    try_times: int = 1
    start_try: int = 1  # New: starting try number (default: 1)
    parallel_tasks: int = 25
    disable_cleanup: bool = False
    disable_initial_cleanup: bool = False  # New flag to control initial cleanup
    enable_logs: bool = False  # New flag to enable log file creation (disabled by default)
    auto_cleanup_logs: bool = True  # New flag to automatically clean up logs on successful completion
    enable_per_task_cleanup: bool = True  # New flag to control per-task Docker cleanup (prevents resource exhaustion)
    
    # Writeup settings
    writeup_mapping_file: Optional[str] = None  # Path to task_writeup_mapping.json
    
    # Model and environment settings
    model_type: str = "aws"  # "aws" or "openai"
    model_name: str = "bedrock:us.anthropic.claude-3-5-sonnet-20241022-v2:0"
    image_name: str = "sweagent/enigma:latest"
    config_file: str = "config/default_ctf.yaml"
    host_url: str = "http://localhost:8000"
    openai_api_key: str = "dummy"
    openai_api_base_url: str = "http://localhost:30000/v1"
    per_instance_step_limit: int = 40
    swe_agent_action_timeout: int = 20
    
    # Model generation parameters
    temperature: float = 0.0
    top_p: float = 0.95
    
    # Execution settings
    max_wait_time: int = 3600
    delay_between_submissions: int = 2
    
    def validate_environment_variables(self):
        """Validate that required environment variables are set based on model type"""
        if self.model_type == "aws":
            required_vars = [
                "ISENGARD_PRODUCTION_ACCOUNT",
                "AWS_ACCESS_KEY_ID", 
                "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN"
            ]
            
            missing_vars = []
            for var in required_vars:
                if not os.environ.get(var):
                    missing_vars.append(var)
            
            if missing_vars:
                raise ValueError(f"Missing required environment variables for AWS model type: {', '.join(missing_vars)}")
            
            logger.info("✅ AWS environment variables validated")
            
        elif self.model_type == "openai":
            required_vars = [
                "OPENAI_API_KEY",
                "OPENAI_API_BASE_URL"
            ]
            
            missing_vars = []
            for var in required_vars:
                if not os.environ.get(var):
                    missing_vars.append(var)
            
            if missing_vars:
                raise ValueError(f"Missing required environment variables for OpenAI model type: {', '.join(missing_vars)}")
            
            logger.info("✅ OpenAI environment variables validated")
            
        else:
            raise ValueError(f"Unsupported model type: {self.model_type}. Must be 'aws' or 'openai'")
    
    def validate_configuration(self):
        """Validate configuration parameters"""
        if self.try_times < 1:
            raise ValueError("try_times must be a positive number")
        
        if self.parallel_tasks < 1:
            raise ValueError("parallel_tasks must be a positive number")
        
        if self.start_try < 1:
            raise ValueError("start_try must be a positive number")
        
        if self.start_try > self.try_times:
            raise ValueError(f"start_try ({self.start_try}) cannot be greater than try_times ({self.try_times})")
        
        logger.info(f"✅ Configuration validated: try_times={self.try_times}, start_try={self.start_try}")
        logger.info(f"✅ Will execute tries {self.start_try} to {self.try_times}")
    
    @classmethod
    def from_yaml(cls, config_path: Path) -> 'RunnerConfig':
        """Load configuration from YAML file"""
        config = cls()
        
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    yaml_config = yaml.safe_load(f)
                
                # Load dataset configuration
                if 'dataset' in yaml_config:
                    dataset_config = yaml_config['dataset']
                    config.dataset_name = dataset_config.get('name', config.dataset_name)
                    config.start_index = dataset_config.get('start_index', config.start_index)
                    config.end_index = dataset_config.get('end_index', config.end_index)
                    config.writeup_mapping_file = dataset_config.get('writeup_mapping_file', config.writeup_mapping_file)
                
                # Update configuration from YAML
                if 'model' in yaml_config:
                    model_config = yaml_config['model']
                    config.model_type = model_config.get('type', config.model_type)
                    config.model_name = model_config.get('name', config.model_name)
                    config.temperature = model_config.get('temperature', config.temperature)
                    config.top_p = model_config.get('top_p', config.top_p)
                
                if 'docker' in yaml_config:
                    docker_config = yaml_config['docker']
                    config.image_name = docker_config.get('image_name', config.image_name)
                    config.per_instance_step_limit = docker_config.get('per_instance_step_limit', config.per_instance_step_limit)
                
                if 'environment' in yaml_config:
                    env_config = yaml_config['environment']
                    config.host_url = env_config.get('host_url', config.host_url)
                    config.openai_api_key = env_config.get('openai_api_key', config.openai_api_key)
                    config.openai_api_base_url = env_config.get('openai_api_base_url', config.openai_api_base_url)
                    config.swe_agent_action_timeout = env_config.get('swe_agent_action_timeout', config.swe_agent_action_timeout)
                
                if 'swe_agent' in yaml_config:
                    swe_config = yaml_config['swe_agent']
                    config.config_file = swe_config.get('config_file', config.config_file)
                
                if 'execution' in yaml_config:
                    exec_config = yaml_config['execution']
                    config.max_wait_time = exec_config.get('max_wait_time', config.max_wait_time)
                    config.delay_between_submissions = exec_config.get('delay_between_submissions', config.delay_between_submissions)
                    config.try_times = exec_config.get('try_times', config.try_times)
                    config.parallel_tasks = exec_config.get('parallel_tasks', config.parallel_tasks)
                    config.disable_cleanup = exec_config.get('disable_cleanup', config.disable_cleanup)
                    config.disable_initial_cleanup = exec_config.get('disable_initial_cleanup', config.disable_initial_cleanup)
                    config.enable_logs = exec_config.get('enable_logs', config.enable_logs)
                    config.auto_cleanup_logs = exec_config.get('auto_cleanup_logs', config.auto_cleanup_logs)
                    config.enable_per_task_cleanup = exec_config.get('enable_per_task_cleanup', config.enable_per_task_cleanup)
                    config.start_try = exec_config.get('start_try', config.start_try)
                
                logger.info(f"Loaded configuration from {config_path}")
                
            except Exception as e:
                logger.warning(f"Failed to load YAML configuration from {config_path}: {e}")
        else:
            logger.warning(f"Configuration file {config_path} not found, using defaults")
        
        return config


class DockerManager:
    """Manages Docker operations for cleanup and container management"""
    
    def __init__(self):
        try:
            self.client = docker.from_env()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            self.client = None
    
    def initial_comprehensive_cleanup(self):
        """Perform comprehensive initial cleanup like the bash script - remove ALL previous CTF resources"""
        if not self.client:
            return
            
        logger.info("🧹 Comprehensive Docker cleanup before starting...")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        # Step 1: Stop and remove ALL non-essential containers first (OPTIMIZED)
        logger.info("🔍 Step 1: Stopping and removing non-essential containers...")
        
        try:
            # Get all containers that are NOT based on lmsysorg/sglang (preserve the LLM server)
            all_containers = self.client.containers.list(all=True)
            containers_to_remove = []
            
            for container in all_containers:
                try:
                    image_name = container.image.tags[0] if container.image.tags else ""
                    if "lmsysorg/sglang" not in image_name:
                        containers_to_remove.append(container)
                except Exception:
                    # If we can't get image info, include it for cleanup
                    containers_to_remove.append(container)
            
            if containers_to_remove:
                logger.info(f"Found {len(containers_to_remove)} containers to remove (preserving lmsysorg/sglang)")
                
                # OPTIMIZATION: Stop all containers in parallel
                logger.info("  🛑 Stopping containers in parallel...")
                stop_futures = []
                with ThreadPoolExecutor(max_workers=10) as executor:
                    for container in containers_to_remove:
                        future = executor.submit(self._stop_container_safe, container)
                        stop_futures.append(future)
                
                # Wait for all stops to complete
                for future in stop_futures:
                    try:
                        future.result(timeout=15)
                    except Exception:
                        pass  # Continue with removal even if stop failed
                
                # Brief wait for graceful shutdown
                time.sleep(2)
                
                # OPTIMIZATION: Remove all containers in parallel
                logger.info("  🗑️  Removing containers in parallel...")
                remove_futures = []
                with ThreadPoolExecutor(max_workers=10) as executor:
                    for container in containers_to_remove:
                        future = executor.submit(self._remove_container_safe, container)
                        remove_futures.append(future)
                
                # Wait for all removals to complete
                for future in remove_futures:
                    try:
                        future.result(timeout=15)
                    except Exception:
                        pass
                
                logger.info("  ✅ Container cleanup completed")
            else:
                logger.info("  ℹ️  No non-essential containers found")
                
        except Exception as e:
            logger.error(f"Error during container cleanup: {e}")
        
        # Step 2: Clean up ALL CTF-related and custom networks (OPTIMIZED)
        logger.info("")
        logger.info("🔍 Step 2: Cleaning up CTF-related and custom networks...")
        
        try:
            # Get all CTF-related networks
            all_networks = self.client.networks.list()
            ctf_networks = []
            
            for network in all_networks:
                if (network.name.startswith('ctfnet') or 
                    network.name.endswith('_default') or 
                    network.name.startswith('tmp_ctfnet')):
                    ctf_networks.append(network)
            
            if ctf_networks:
                logger.info(f"Found {len(ctf_networks)} CTF networks to clean up")
                
                # OPTIMIZATION: Disconnect all containers from all networks in parallel
                logger.info("  🔌 Mass disconnecting containers from networks...")
                disconnect_futures = []
                with ThreadPoolExecutor(max_workers=5) as executor:
                    for network in ctf_networks:
                        future = executor.submit(self._disconnect_network_safe, network)
                        disconnect_futures.append(future)
                
                # Wait for all disconnections to complete
                for future in disconnect_futures:
                    try:
                        future.result(timeout=30)
                    except Exception:
                        pass
                
                # Brief pause to let disconnections complete
                time.sleep(1)
                
                # OPTIMIZATION: Remove all networks in parallel
                logger.info("  🗑️  Removing networks in parallel...")
                remove_futures = []
                with ThreadPoolExecutor(max_workers=5) as executor:
                    for network in ctf_networks:
                        future = executor.submit(self._remove_network_safe, network)
                        remove_futures.append(future)
                
                # Wait for all removals to complete
                for future in remove_futures:
                    try:
                        future.result(timeout=15)
                    except Exception:
                        pass
                
                logger.info("  ✅ Network cleanup completed")
            else:
                logger.info("  ℹ️  No CTF-related networks found")
                
        except Exception as e:
            logger.error(f"Error during network cleanup: {e}")
        
        # Step 3: Prune unused Docker resources (OPTIMIZED)
        logger.info("")
        logger.info("🔍 Step 3: Pruning unused Docker resources...")
        
        try:
            # OPTIMIZATION: Prune networks and volumes in parallel
            with ThreadPoolExecutor(max_workers=2) as executor:
                # Prune networks (removes unused networks)
                logger.info("  🌐 Pruning unused networks...")
                network_future = executor.submit(self.client.networks.prune)
                
                # Prune volumes (removes unused volumes)
                logger.info("  💾 Pruning unused volumes...")
                volume_future = executor.submit(self.client.volumes.prune)
                
                # Wait for both to complete
                try:
                    network_future.result(timeout=30)
                    volume_future.result(timeout=30)
                except Exception:
                    pass
            
        except Exception as e:
            logger.error(f"Error pruning Docker resources: {e}")
        
        # Show remaining resources for verification (OPTIMIZED - reduced logging)
        logger.info("")
        logger.info("📊 Remaining Docker resources after cleanup:")
        
        try:
            remaining_containers = self.client.containers.list(all=True)
            logger.info(f"  Containers: {len(remaining_containers)}")
            if remaining_containers:
                for container in remaining_containers[:3]:  # Show only first 3
                    logger.info(f"    {container.name}\t{container.image.tags[0] if container.image.tags else 'unknown'}\t{container.status}")
                if len(remaining_containers) > 3:
                    logger.info(f"    ... and {len(remaining_containers) - 3} more")
            else:
                logger.info("    No containers found")
            
            remaining_networks = self.client.networks.list()
            logger.info(f"  Networks: {len(remaining_networks)}")
            for network in remaining_networks[:5]:  # Show only first 5
                logger.info(f"    {network.name}\t{network.attrs.get('Driver', 'unknown')}")
            if len(remaining_networks) > 5:
                logger.info(f"    ... and {len(remaining_networks) - 5} more")
                
        except Exception as e:
            logger.error(f"Error showing remaining resources: {e}")
        
        logger.info("")
        logger.info("✅ Comprehensive initial cleanup completed")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("")
    
    def cleanup_containers(self, execution_id: str):
        """Clean up containers from this execution (OPTIMIZED)"""
        if not self.client:
            return
            
        try:
            # Get all containers from this execution
            containers = self.client.containers.list(
                all=True,
                filters={"name": f"{execution_id}-parallel-"}
            )
            
            if containers:
                logger.info(f"Cleaning up {len(containers)} containers from execution {execution_id}")
                
                # OPTIMIZATION: Stop and remove containers in parallel
                cleanup_futures = []
                with ThreadPoolExecutor(max_workers=5) as executor:
                    for container in containers:
                        future = executor.submit(self._cleanup_container_execution, container)
                        cleanup_futures.append(future)
                
                # Wait for all cleanups to complete
                for future in cleanup_futures:
                    try:
                        future.result(timeout=15)
                    except Exception:
                        pass
                
        except Exception as e:
            logger.error(f"Error cleaning up containers: {e}")
    
    def cleanup_networks(self, execution_id: str):
        """Clean up networks from this execution (OPTIMIZED)"""
        if not self.client:
            return
            
        try:
            # Get all networks from this execution
            networks = self.client.networks.list(
                filters={"name": f"{execution_id}"}
            )
            
            if networks:
                logger.info(f"Cleaning up {len(networks)} networks from execution {execution_id}")
                
                # OPTIMIZATION: Remove networks in parallel
                cleanup_futures = []
                with ThreadPoolExecutor(max_workers=5) as executor:
                    for network in networks:
                        future = executor.submit(self._cleanup_network_execution, network)
                        cleanup_futures.append(future)
                
                # Wait for all cleanups to complete
                for future in cleanup_futures:
                    try:
                        future.result(timeout=15)
                    except Exception:
                        pass
                
        except Exception as e:
            logger.error(f"Error cleaning up networks: {e}")
    
    def _cleanup_container_execution(self, container):
        """Clean up a single container from execution (with reduced logging)"""
        try:
            # Handle different container states
            if container.status == 'running':
                container.stop(timeout=5)
            elif container.status == 'paused':
                # Unpause first, then stop
                container.unpause()
                container.stop(timeout=5)
            elif container.status in ['exited', 'dead']:
                # Container already stopped, just remove
                pass
            else:
                # For other states, try to stop anyway
                try:
                    container.stop(timeout=5)
                except Exception:
                    pass  # Continue with removal
            
            # Force remove the container
            container.remove(force=True)
            return True
        except Exception as e:
            logger.debug(f"Failed to clean up container {container.name}: {e}")
            return False
    
    def _cleanup_network_execution(self, network):
        """Clean up a single network from execution (with reduced logging)"""
        try:
            network.remove()
            return True
        except Exception:
            return False
    
    def comprehensive_cleanup(self, execution_id: str):
        """Perform comprehensive cleanup of all Docker resources"""
        if not self.client:
            return
            
        logger.info("🧹 Starting comprehensive Docker cleanup...")
        
        # Clean up containers
        self.cleanup_containers(execution_id)
        
        # Clean up networks
        self.cleanup_networks(execution_id)
        
        # Prune unused resources
        try:
            self.client.networks.prune()
            self.client.volumes.prune()
        except Exception as e:
            logger.error(f"Error pruning Docker resources: {e}")
        
        logger.info("✅ Docker cleanup completed")

    def _stop_container_safe(self, container):
        """Safely stop a container with timeout"""
        try:
            # Handle different container states
            if container.status == 'running':
                container.stop(timeout=5)  # Reduced timeout
            elif container.status == 'paused':
                # Unpause first, then stop
                container.unpause()
                container.stop(timeout=5)
            elif container.status in ['exited', 'dead']:
                # Container already stopped, just return
                return True
            else:
                # For other states, try to stop anyway
                container.stop(timeout=5)
            return True
        except Exception as e:
            logger.debug(f"Failed to stop container {container.name}: {e}")
            return False
    
    def _remove_container_safe(self, container):
        """Safely remove a container with timeout"""
        try:
            # Force remove regardless of state
            container.remove(force=True)
            return True
        except Exception as e:
            logger.debug(f"Failed to remove container {container.name}: {e}")
            return False
    
    def _disconnect_network_safe(self, network):
        """Safely disconnect all containers from a network"""
        try:
            network.reload()
            containers = network.attrs.get('Containers', {})
            if containers:
                for container_id in containers.keys():
                    try:
                        container = self.client.containers.get(container_id)
                        network.disconnect(container, force=True)
                    except Exception:
                        pass  # Continue with other containers
            return True
        except Exception:
            return False
    
    def _remove_network_safe(self, network):
        """Safely remove a network"""
        try:
            network.remove()
            return True
        except Exception:
            return False
    
    def _cleanup_network_proactive(self, network):
        """Clean up a network during proactive cleanup (with reduced logging)"""
        try:
            logger.info(f"Removing leftover network: {network.name}")
            # First disconnect any containers
            network.reload()
            containers = network.attrs.get('Containers', {})
            for container_id, container_info in containers.items():
                try:
                    container = self.client.containers.get(container_id)
                    network.disconnect(container, force=True)
                except Exception:
                    pass  # Continue with other containers
            
            # Remove the network
            network.remove()
            return True
        except Exception as e:
            logger.warning(f"Failed to remove leftover network {network.name}: {e}")
            return False
    
    def cleanup_task_resources(self, session_name: str, execution_id: str):
        """Clean up Docker resources for a specific task based on session name"""
        if not self.client:
            return
        
        try:
            # Extract task information from session name
            # Session name format: swe_{execution_id}_{instance_id}_{challenge_id}_try{try_num}
            parts = session_name.split('_')
            if len(parts) >= 5:
                # Extract instance_id and challenge_id from session name
                instance_id = parts[2]  # After execution_id
                challenge_id = parts[3]  # Before try{try_num}
                try_num = parts[4].replace('try', '')  # Extract try number
                
                # Clean up the specific container for this task
                container_name = f"{execution_id}-parallel-{instance_id}-{challenge_id}-try{try_num}"
                self._cleanup_task_container(container_name)
                
                # Clean up any networks associated with this task
                self._cleanup_task_networks(execution_id, instance_id, challenge_id, try_num)
                
                logger.debug(f"Cleaned up Docker resources for task: {session_name}")
            else:
                logger.warning(f"Could not parse session name for cleanup: {session_name}")
                
        except Exception as e:
            logger.error(f"Error cleaning up task resources for {session_name}: {e}")
    
    def _cleanup_task_container(self, container_name: str):
        """Clean up a specific container by name"""
        try:
            container = self.client.containers.get(container_name)
            logger.debug(f"Cleaning up container: {container_name}")
            
            # Handle different container states
            if container.status == 'running':
                container.stop(timeout=5)
            elif container.status == 'paused':
                # Unpause first, then stop
                container.unpause()
                container.stop(timeout=5)
            elif container.status in ['exited', 'dead']:
                # Container already stopped, just remove
                pass
            else:
                # For other states, try to stop anyway
                try:
                    container.stop(timeout=5)
                except Exception:
                    pass  # Continue with removal
            
            # Force remove the container
            container.remove(force=True)
            logger.debug(f"Successfully removed container: {container_name}")
            
        except docker.errors.NotFound:
            logger.debug(f"Container not found (already cleaned up): {container_name}")
        except Exception as e:
            logger.warning(f"Failed to clean up container {container_name}: {e}")
    
    def _cleanup_task_networks(self, execution_id: str, instance_id: str, challenge_id: str, try_num: str):
        """Clean up networks associated with a specific task"""
        try:
            # Look for networks that might be associated with this task
            # Common patterns: ctfnet_{execution_id}_{instance_id}, tmp_ctfnet_{execution_id}_{instance_id}
            network_patterns = [
                f"ctfnet_{execution_id}_{instance_id}",
                f"tmp_ctfnet_{execution_id}_{instance_id}",
                f"{execution_id}_{instance_id}_default",
                f"ctfnet_{challenge_id}_{try_num}",
                f"tmp_ctfnet_{challenge_id}_{try_num}"
            ]
            
            all_networks = self.client.networks.list()
            cleaned_networks = []
            
            for network in all_networks:
                for pattern in network_patterns:
                    if pattern in network.name:
                        try:
                            logger.debug(f"Cleaning up network: {network.name}")
                            
                            # Disconnect any containers from this network
                            network.reload()
                            containers = network.attrs.get('Containers', {})
                            for container_id in containers.keys():
                                try:
                                    container = self.client.containers.get(container_id)
                                    network.disconnect(container, force=True)
                                except Exception:
                                    pass  # Continue with other containers
                            
                            # Remove the network
                            network.remove()
                            cleaned_networks.append(network.name)
                            logger.debug(f"Successfully removed network: {network.name}")
                            break  # Don't try other patterns for this network
                            
                        except Exception as e:
                            logger.warning(f"Failed to clean up network {network.name}: {e}")
            
            if cleaned_networks:
                logger.debug(f"Cleaned up {len(cleaned_networks)} networks for task {instance_id}_{challenge_id}_try{try_num}")
                
        except Exception as e:
            logger.error(f"Error cleaning up task networks: {e}")


class TmuxManager:
    """Manages tmux sessions for parallel execution"""
    
    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.session_prefix = f"swe_{execution_id}"  # Shortened prefix
        self.active_sessions = set()
        self.session_lock = threading.Lock()
    
    def create_session(self, session_name: str, command: str, log_file: Path = None, status_file: Path = None) -> bool:
        """Create a new tmux session with the given command"""
        try:
            # Create a temporary script file for the command
            script_content = f"""#!/bin/bash
# Auto-generated script for tmux session: {session_name}
set -e
set -x  # Enable debugging to see what's happening

echo "Starting tmux session: {session_name}"
echo "Working directory: $(pwd)"

# Change to the correct directory
cd "{Path.cwd()}"
echo "Changed to directory: $(pwd)"

# Check if run.py exists
if [ ! -f "run.py" ]; then
    echo "ERROR: run.py not found in $(pwd)"
    ls -la
    echo "COMPLETED_FAILED" > "{status_file if status_file else '/dev/null'}"
    exit 1
fi

# Check if Python is available
if ! command -v python &> /dev/null; then
    echo "ERROR: python command not found"
    which python3 || echo "python3 also not found"
    echo "COMPLETED_FAILED" > "{status_file if status_file else '/dev/null'}"
    exit 1
fi

# Initialize status file
echo "RUNNING" > "{status_file if status_file else '/dev/null'}"

# Write command to a temporary file to avoid escaping issues
cat > /tmp/command_{session_name}.sh << 'COMMAND_EOF'
{command}
COMMAND_EOF

# Make the command file executable
chmod +x /tmp/command_{session_name}.sh

# Validate the command file syntax
if ! bash -n /tmp/command_{session_name}.sh; then
    echo "ERROR: Command file has syntax errors"
    echo "COMPLETED_FAILED" > "{status_file if status_file else '/dev/null'}"
    rm -f /tmp/command_{session_name}.sh
    exit 1
fi

# Execute the command with comprehensive error handling
set +e  # Don't exit on error, we'll handle it manually
if [ -n "{log_file if log_file else ''}" ]; then
    bash /tmp/command_{session_name}.sh 2>&1 | tee -a "{log_file}"
else
    bash /tmp/command_{session_name}.sh 2>&1
fi
exit_code=$?
set -e  # Re-enable exit on error

echo "Command completed with exit code: $exit_code"

# Check for specific error patterns in the output that indicate Docker issues
if [ $exit_code -ne 0 ]; then
    # Check if the error was a Docker network issue
    if [ -n "{log_file if log_file else ''}" ] && [ -f "{log_file}" ]; then
        if grep -q "failed to create endpoint.*on network.*exchange full" "{log_file}" || \
           grep -q "docker.errors.APIError.*500 Server Error" "{log_file}" || \
           grep -q "failed to create endpoint" "{log_file}"; then
            echo "DETECTED: Docker network error (exchange full) - marking as failed"
            echo "COMPLETED_FAILED" > "{status_file if status_file else '/dev/null'}"
            rm -f /tmp/command_{session_name}.sh
            exit 1
        fi
    fi
    
    # Check for other common Docker errors
    if [ -n "{log_file if log_file else ''}" ] && [ -f "{log_file}" ]; then
        if grep -q "docker.errors" "{log_file}" || \
           grep -q "Internal Server Error" "{log_file}" || \
           grep -q "failed to create endpoint" "{log_file}"; then
            echo "DETECTED: Docker error - marking as failed"
            echo "COMPLETED_FAILED" > "{status_file if status_file else '/dev/null'}"
            rm -f /tmp/command_{session_name}.sh
            exit 1
        fi
    fi
fi

# Update status based on exit code
if [ $exit_code -eq 0 ]; then
    echo "COMPLETED_SUCCESS" > "{status_file if status_file else '/dev/null'}"
    echo "Challenge completed successfully"
else
    echo "COMPLETED_FAILED" > "{status_file if status_file else '/dev/null'}"
    echo "Challenge failed with exit code: $exit_code"
fi

# Clean up command file
rm -f /tmp/command_{session_name}.sh

# Keep session alive for a moment to capture any final output
sleep 2

# Exit with the same code as the command
exit $exit_code
"""
            
            # Write script to a temporary file
            script_file = Path(f"/tmp/tmux_script_{session_name}.sh")
            with open(script_file, 'w') as f:
                f.write(script_content)
            
            # Make script executable
            script_file.chmod(0o755)
            
            # Validate the script syntax before creating tmux session
            try:
                result = subprocess.run(['bash', '-n', str(script_file)], 
                                      capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    logger.error(f"Generated script has syntax errors: {result.stderr}")
                    script_file.unlink()
                    return False
            except subprocess.TimeoutExpired:
                logger.error(f"Script validation timed out")
                script_file.unlink()
                return False
            except Exception as e:
                logger.error(f"Error validating script: {e}")
                script_file.unlink()
                return False
            
            # Create new session
            result = subprocess.run([
                'tmux', 'new-session', '-d', '-s', session_name,
                '-c', str(Path.cwd())
            ], capture_output=True, text=True, check=True)
            
            # Send the script execution command to the session
            subprocess.run([
                'tmux', 'send-keys', '-t', session_name, f'bash {script_file}', 'Enter'
            ], capture_output=True, text=True, check=True)
            
            # Wait a moment to ensure the session is properly started
            time.sleep(1)
            
            with self.session_lock:
                self.active_sessions.add(session_name)
            
            logger.info(f"Created tmux session: {session_name}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create tmux session {session_name}: {e}")
            # Clean up script file if it exists
            script_file = Path(f"/tmp/tmux_script_{session_name}.sh")
            if script_file.exists():
                script_file.unlink()
            return False
        except Exception as e:
            logger.error(f"Unexpected error creating tmux session {session_name}: {e}")
            # Clean up script file if it exists
            script_file = Path(f"/tmp/tmux_script_{session_name}.sh")
            if script_file.exists():
                script_file.unlink()
            return False
    
    def kill_session(self, session_name: str):
        """Kill a tmux session"""
        try:
            subprocess.run(['tmux', 'kill-session', '-t', session_name], 
                         capture_output=True, text=True, check=True)
            
            with self.session_lock:
                self.active_sessions.discard(session_name)
                
            logger.info(f"Killed tmux session: {session_name}")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to kill tmux session {session_name}: {e}")
    
    def list_sessions(self) -> List[str]:
        """List all active sessions with our prefix"""
        try:
            result = subprocess.run(
                ['tmux', 'list-sessions', '-F', '#{session_name}'],
                capture_output=True, text=True, check=True
            )
            
            sessions = []
            for line in result.stdout.strip().split('\n'):
                if line and line.startswith(self.session_prefix):
                    sessions.append(line)
            
            return sessions
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to list tmux sessions: {e}")
            return []
    
    def cleanup_all_sessions(self):
        """Clean up all sessions with our prefix"""
        sessions = self.list_sessions()
        for session in sessions:
            self.kill_session(session)
        
        # Clean up temporary script files
        script_pattern = f"/tmp/tmux_script_{self.session_prefix}_*.sh"
        for script_file in glob.glob(script_pattern):
            try:
                Path(script_file).unlink()
                logger.debug(f"Cleaned up script file: {script_file}")
            except Exception as e:
                logger.warning(f"Failed to clean up script file {script_file}: {e}")
        
        logger.info(f"Cleaned up {len(sessions)} tmux sessions")


class ChallengeRunner:
    """Main class for running CTF challenges in parallel"""
    
    def __init__(self, config: RunnerConfig):
        self.config = config
        self.execution_id = self._generate_execution_id()
        self.docker_manager = DockerManager()
        self.tmux_manager = TmuxManager(self.execution_id)
        
        # Setup paths
        self.script_dir = Path(__file__).parent.absolute()
        self.dataset_json = self.script_dir.parent / "gym-env" / f"{config.dataset_name}.json"
        self.logs_dir = self.script_dir / "logs"
        self.logs_dir.mkdir(exist_ok=True)
        
        # Status file tracking (like bash script)
        self.active_sessions_file = self.logs_dir / f"active_sessions_{self.execution_id}.txt"
        self.status_file_prefix = self.logs_dir / f"status_{self.execution_id}"
        
        # Load challenges
        self.challenges = self._load_challenges()
        
        # Load writeup mapping if provided
        self.writeup_mapping = {}
        if self.config.writeup_mapping_file:
            self._load_writeup_mapping()
        
        # Statistics
        self.total_jobs = 0
        self.completed_jobs = 0
        self.failed_jobs = 0
        self.start_time = time.time()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _generate_execution_id(self) -> str:
        """Generate a unique execution ID"""
        machine_id = os.uname().nodename.split('.')[0]  # Use only the first part of hostname
        process_id = os.getpid()
        timestamp = int(time.time()) % 1000000  # Use shorter timestamp
        return f"{machine_id}_{process_id}_{timestamp}"
    
    def _load_challenges(self) -> List[Tuple[str, str]]:
        """Load challenges from the dataset JSON file"""
        if not self.dataset_json.exists():
            raise FileNotFoundError(f"Dataset file not found: {self.dataset_json}")
        
        with open(self.dataset_json, 'r') as f:
            data = json.load(f)
        
        challenges = []
        for challenge_id, challenge_data in data.items():
            challenges.append((challenge_id, challenge_data['path']))
        
        # Apply index filtering
        if self.config.start_index is not None:
            if self.config.end_index is not None:
                # Range of challenges
                start_idx = self.config.start_index - 1  # Convert to 0-based
                end_idx = self.config.end_index
                challenges = challenges[start_idx:end_idx]
            else:
                # Single challenge
                idx = self.config.start_index - 1  # Convert to 0-based
                challenges = [challenges[idx]]
        
        return challenges
    
    def _load_writeup_mapping(self):
        """Load the writeup mapping from a JSON file."""
        try:
            with open(self.config.writeup_mapping_file, 'r') as f:
                self.writeup_mapping = json.load(f)
            logger.info(f"Loaded writeup mapping from {self.config.writeup_mapping_file}")
        except FileNotFoundError:
            logger.warning(f"Writeup mapping file not found: {self.config.writeup_mapping_file}. Writeups will not be generated.")
        except Exception as e:
            logger.error(f"Error loading writeup mapping from {self.config.writeup_mapping_file}: {e}")
    
    def _get_random_writeup(self, challenge_id: str) -> Optional[str]:
        """Get a random writeup for the given challenge ID."""
        if not self.writeup_mapping or 'task_writeup_mapping' not in self.writeup_mapping:
            return None
        
        task_mapping = self.writeup_mapping['task_writeup_mapping']
        
        # Look for the challenge in the mapping
        if challenge_id in task_mapping:
            writeups = task_mapping[challenge_id].get('writeups', [])
            if writeups:
                # Randomly sample one writeup
                selected_writeup = random.choice(writeups)
                return selected_writeup.get('task_writeup', '')
        
        return None
    
    def _signal_handler(self, signum, frame):
        """Handle cleanup on signal"""
        logger.info("Received signal, starting cleanup...")
        self.cleanup()
        sys.exit(1)
    
    def _build_run_command(self, challenge_id: str, challenge_path: str, 
                          try_num: int, instance_id: int) -> str:
        """Build the command to run a single challenge"""
        
        # Construct absolute paths
        workspace_root = self.script_dir
        ctf_bench_root = workspace_root.parent / "gym-env"
        data_path = ctf_bench_root / challenge_path / "challenge.json"
        repo_path = ctf_bench_root / challenge_path
        
        # Create unique container name
        container_name = f"{self.execution_id}-parallel-{instance_id}-{challenge_id}-try{try_num}"
        
        # Get writeup if available
        writeup_content = self._get_random_writeup(challenge_id)
        
        # Build the command
        cmd_parts = [
            "python", "run.py",
            "--model_name", self.config.model_name,
            "--ctf",
            "--image_name", self.config.image_name,
            "--data_path", str(data_path),
            "--repo_path", str(repo_path),
            "--config_file", self.config.config_file,
            "--host_url", self.config.host_url,
            "--per_instance_step_limit", str(self.config.per_instance_step_limit),
            "--trajectory_path", f"trajectories/{self.config.dataset_name}/try{try_num}",
            "--temperature", str(self.config.temperature),
            "--top_p", str(self.config.top_p),
            "--enable_dynamic_ports",
            "--container_name", container_name,
            "--allow_dirty_repo"
        ]
        
        # Add writeup if available
        if writeup_content:
            # Escape the writeup content for shell command
            escaped_writeup = writeup_content.replace("'", "'\"'\"'")
            cmd_parts.extend(["--writeup", f"'{escaped_writeup}'"])
            logger.debug(f"Added writeup for challenge {challenge_id}")
        
        # Build environment export commands based on model type
        env_exports = [
            f"export SWE_AGENT_ACTION_TIMEOUT={self.config.swe_agent_action_timeout}"
        ]
        
        if self.config.model_type == "aws":
            # Use environment variables for AWS credentials
            env_exports.extend([
                "export ISENGARD_PRODUCTION_ACCOUNT=true",
                f"export AWS_ACCESS_KEY_ID='{os.environ['AWS_ACCESS_KEY_ID']}'",
                f"export AWS_SECRET_ACCESS_KEY='{os.environ['AWS_SECRET_ACCESS_KEY']}'",
                f"export AWS_SESSION_TOKEN='{os.environ['AWS_SESSION_TOKEN']}'"
            ])
        elif self.config.model_type == "openai":
            # Use environment variables for OpenAI credentials
            env_exports.extend([
                f"export OPENAI_API_KEY='{os.environ['OPENAI_API_KEY']}'",
                f"export OPENAI_API_BASE_URL='{os.environ['OPENAI_API_BASE_URL']}'"
            ])
        
        # Combine into final command using export commands directly
        env_str = " && ".join(env_exports)
        cmd_str = " ".join(cmd_parts)
        final_command = f"{env_str} && {cmd_str}"
        
        logger.debug(f"Final command: {final_command}")
        
        return final_command
    
    def run_challenge(self, challenge_id: str, challenge_path: str, 
                     try_num: int, instance_id: int) -> bool:
        """Run a single challenge directly in current session (for testing)"""
        
        # Build the command
        command = self._build_run_command(challenge_id, challenge_path, try_num, instance_id)
        
        # Create log file only if logs are enabled
        if self.config.enable_logs:
            log_file = self.logs_dir / f"{self.execution_id}_parallel_{instance_id}_{challenge_id}_try{try_num}.log"
            # Add logging to command
            command = f"{command} 2>&1 | tee -a {log_file}"
        
        logger.info(f"Starting challenge: {challenge_id} (try {try_num}) directly in current session")
        logger.info(f"Command: {command}")
        
        try:
            # Run the command directly
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                logger.info(f"Challenge {challenge_id} (try {try_num}) completed successfully")
                return True
            else:
                logger.error(f"Challenge {challenge_id} (try {try_num}) failed with return code {result.returncode}")
                logger.error(f"Error output: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"Challenge {challenge_id} (try {try_num}) timed out")
            return False
        except Exception as e:
            logger.error(f"Error running challenge {challenge_id} (try {try_num}): {e}")
            return False
    
    def wait_for_completion(self, max_wait_time: int = None) -> None:
        """Wait for all active sessions to complete"""
        if max_wait_time is None:
            max_wait_time = self.config.max_wait_time
            
        start_time = time.time()
        last_check_time = start_time
        last_aggressive_cleanup = start_time
        
        while time.time() - start_time < max_wait_time:
            # Clean up finished sessions
            self.cleanup_finished_sessions()
            
            # Count active sessions
            active_sessions = len(self.tmux_manager.active_sessions)
            
            if active_sessions == 0:
                logger.info("All sessions completed")
                break
            
            # Log progress every 30 seconds
            if time.time() - last_check_time > 30:
                logger.info(f"⏳ Still waiting for {active_sessions} active sessions...")
                last_check_time = time.time()
            
            # Perform aggressive cleanup every 5 minutes to catch stuck sessions
            if time.time() - last_aggressive_cleanup > 300:  # 5 minutes
                logger.info("🔍 Performing aggressive cleanup check for stuck sessions...")
                self._aggressive_cleanup_stuck_sessions()
                last_aggressive_cleanup = time.time()
            
            time.sleep(10)
        
        if time.time() - start_time >= max_wait_time:
            logger.warning("Timeout reached, forcing cleanup of remaining sessions")
            self.tmux_manager.cleanup_all_sessions()
    
    def _aggressive_cleanup_stuck_sessions(self):
        """Aggressively clean up sessions that appear to be stuck"""
        if not self.active_sessions_file.exists():
            return
        
        try:
            with open(self.active_sessions_file, 'r') as f:
                lines = f.readlines()
            
            stuck_sessions = []
            for line in lines:
                if ':' not in line.strip():
                    continue
                
                session_name, status_file = line.strip().split(':', 1)
                status_path = Path(status_file)
                
                # Check if session exists
                try:
                    result = subprocess.run([
                        'tmux', 'has-session', '-t', session_name
                    ], capture_output=True, text=True)
                    
                    if result.returncode == 0:
                        # Session exists, check if it's been running too long
                        if status_path.exists():
                            try:
                                stat = status_path.stat()
                                # If status file hasn't been updated in 30 minutes, consider it stuck
                                if time.time() - stat.st_mtime > 1800:  # 30 minutes
                                    stuck_sessions.append((session_name, status_path, "status_file_stale"))
                            except Exception:
                                stuck_sessions.append((session_name, status_path, "status_file_error"))
                        else:
                            # No status file, check if session has been running too long
                            # Assume it started 10 minutes ago if no status file
                            session_start_time = time.time() - 600
                            if time.time() - session_start_time > 2400:  # 40 minutes total
                                stuck_sessions.append((session_name, status_path, "no_status_file"))
                except Exception:
                    pass
            
            # Force cleanup of stuck sessions
            for session_name, status_path, reason in stuck_sessions:
                logger.warning(f"Force killing stuck session {session_name} (reason: {reason})")
                try:
                    # Update status to failed
                    status_path.parent.mkdir(exist_ok=True)
                    with open(status_path, 'w') as sf:
                        sf.write("COMPLETED_FAILED")
                except Exception:
                    pass
                
                # Kill the session
                self.tmux_manager.kill_session(session_name)
                
                # Clean up Docker resources for stuck session
                if self.config.enable_per_task_cleanup:
                    logger.debug(f"Cleaning up Docker resources for stuck session: {session_name}")
                    self.docker_manager.cleanup_task_resources(session_name, self.execution_id)
            
            if stuck_sessions:
                logger.info(f"Cleaned up {len(stuck_sessions)} stuck sessions")
                
        except Exception as e:
            logger.error(f"Error during aggressive cleanup: {e}")
    
    def run_parallel(self) -> None:
        """Run challenges in parallel using tmux sessions"""
        logger.info(f"🚀 Starting parallel execution with tmux sessions")
        logger.info(f"📊 Total challenges: {len(self.challenges)}")
        logger.info(f"🔄 Try times: {self.config.try_times}")
        logger.info(f"🎯 Start try: {self.config.start_try}")
        logger.info(f"📈 Try range: {self.config.start_try} to {self.config.try_times}")
        logger.info(f"⚡ Parallel tasks: {self.config.parallel_tasks}")
        logger.info(f"🧹 Disable cleanup: {self.config.disable_cleanup}")
        logger.info(f"🧹 Disable initial cleanup: {self.config.disable_initial_cleanup}")
        logger.info(f"🧹 Enable logs: {self.config.enable_logs}")
        logger.info(f"🧹 Auto cleanup logs: {self.config.auto_cleanup_logs}")
        logger.info(f"🧹 Enable per-task cleanup: {self.config.enable_per_task_cleanup}")
        
        # Log writeup statistics if writeup mapping is loaded
        if self.writeup_mapping and 'task_writeup_mapping' in self.writeup_mapping:
            total_tasks_with_writeups = len(self.writeup_mapping['task_writeup_mapping'])
            challenges_with_writeups = sum(1 for challenge_id, _ in self.challenges 
                                         if challenge_id in self.writeup_mapping['task_writeup_mapping'])
            logger.info(f"📚 Writeup mapping loaded: {total_tasks_with_writeups} total tasks with writeups")
            logger.info(f"📚 Challenges with writeups: {challenges_with_writeups}/{len(self.challenges)}")
        elif self.config.writeup_mapping_file:
            logger.info("📚 Writeup mapping file specified but not loaded")
        else:
            logger.info("📚 No writeup mapping file specified - running without writeups")
        
        # CRITICAL: Perform comprehensive initial cleanup like the bash script
        if not self.config.disable_initial_cleanup:
            logger.info("🧹 Performing comprehensive initial cleanup before starting...")
            self.docker_manager.initial_comprehensive_cleanup()
            
            # Clean up any existing tmux sessions from previous runs
            logger.info("🧹 Cleaning up any existing tmux sessions...")
            self.tmux_manager.cleanup_all_sessions()
            
            # Proactive cleanup of leftover networks from previous runs
            logger.info("🧹 Performing proactive cleanup of leftover networks...")
            try:
                leftover_networks = []
                for network in self.docker_manager.client.networks.list():
                    if (network.name.startswith('ctfnet') or 
                        network.name.startswith('tmp_ctfnet')):
                        leftover_networks.append(network)
                
                if leftover_networks:
                    logger.warning(f"⚠️  Found {len(leftover_networks)} leftover CTF networks from previous runs")
                    logger.info("Cleaning them up to prevent subnet exhaustion...")
                    
                    # OPTIMIZATION: Clean up networks in parallel
                    cleanup_futures = []
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        for network in leftover_networks:
                            future = executor.submit(self._cleanup_network_proactive, network)
                            cleanup_futures.append(future)
                    
                    # Wait for all cleanups to complete
                    for future in cleanup_futures:
                        try:
                            future.result(timeout=30)
                        except Exception:
                            pass
                    
                    logger.info("✅ Proactive cleanup completed")
                else:
                    logger.info("✅ No leftover CTF networks found - starting clean")
                
                # Check Docker subnet availability
                total_networks = len([n for n in self.docker_manager.client.networks.list() if n.attrs.get('Driver') == 'bridge'])
                if total_networks > 20:
                    logger.warning(f"⚠️  Warning: Found {total_networks} bridge networks, approaching Docker subnet limits")
                    logger.info("Consider running a full cleanup if you encounter network creation errors")
                    logger.info("ℹ️  Note: The system now automatically waits for subnet space (up to 15 minutes) instead of failing immediately")
                    
            except Exception as e:
                logger.warning(f"Error during proactive cleanup: {e}")
        else:
            logger.info("🚫 Initial Docker cleanup disabled - skipping proactive cleanup")
        
        # Initialize active sessions file
        with open(self.active_sessions_file, 'w') as f:
            pass  # Create empty file
        
        # Run challenges by try number
        total_tries = self.config.try_times - self.config.start_try + 1
        current_try = 0
        
        for try_num in range(self.config.start_try, self.config.try_times + 1):
            current_try += 1
            logger.info(f"🔁 Starting Try {try_num} ({current_try}/{total_tries}) of range {self.config.start_try}-{self.config.try_times}")
            
            # Create a pool of tasks for this try
            tasks = []
            instance_id = 0
            
            for challenge_id, challenge_path in self.challenges:
                instance_id += 1
                self.total_jobs += 1
                
                # Build the command
                command = self._build_run_command(challenge_id, challenge_path, try_num, instance_id)
                
                # Create log file only if logs are enabled
                log_file = None
                if self.config.enable_logs:
                    log_file = self.logs_dir / f"{self.execution_id}_parallel_{instance_id}_{challenge_id}_try{try_num}.log"
                
                # Create status file
                status_file = self.status_file_prefix / f"{instance_id}_{challenge_id}_try{try_num}.txt"
                status_file.parent.mkdir(exist_ok=True)
                
                # Create unique session name
                session_name = f"{self.tmux_manager.session_prefix}_{instance_id}_{challenge_id}_try{try_num}"
                
                # Add to task list with log file and status file
                tasks.append((session_name, command, challenge_id, try_num, log_file, status_file))
            
            # Submit tasks in parallel (respecting parallel_tasks limit)
            active_sessions = 0
            completed_tasks = 0
            
            for session_name, command, challenge_id, try_num, log_file, status_file in tasks:
                # Wait if we've reached the parallel limit
                while active_sessions >= self.config.parallel_tasks:
                    # Clean up finished sessions
                    self.cleanup_finished_sessions()
                    
                    # Count active sessions
                    active_sessions = len(self.tmux_manager.active_sessions)
                    
                    if active_sessions >= self.config.parallel_tasks:
                        time.sleep(5)  # Wait before checking again
                
                # Submit new task
                logger.info(f"🚀 Starting challenge: {challenge_id} (try {try_num}) in tmux session: {session_name}")
                
                if self.tmux_manager.create_session(session_name, command, log_file, status_file):
                    active_sessions += 1
                    logger.info(f"📈 Active sessions: {active_sessions}/{self.config.parallel_tasks}")
                    
                    # Store session info for tracking
                    with open(self.active_sessions_file, 'a') as f:
                        f.write(f"{session_name}:{status_file}\n")
                else:
                    logger.error(f"❌ Failed to start challenge: {challenge_id}")
                    self.failed_jobs += 1
                
                # Small delay between submissions
                time.sleep(self.config.delay_between_submissions)
            
            # Wait for all remaining sessions to complete
            logger.info(f"⏳ Waiting for {active_sessions} remaining sessions to complete...")
            self.wait_for_completion()
            
            logger.info(f"✅ Try {try_num} ({current_try}/{total_tries}) completed")
        
        # Final cleanup
        if not self.config.disable_cleanup:
            self.docker_manager.comprehensive_cleanup(self.execution_id)
        
        # Clean up logs directory if all tasks completed successfully
        self.cleanup_logs_directory()
    
    def cleanup_logs_directory(self) -> None:
        """Clean up the logs directory when all tasks have completed successfully"""
        if not self.config.auto_cleanup_logs:
            logger.info("🚫 Auto-cleanup of logs is disabled. Keeping logs for debugging.")
            return

        try:
            # Check if all status files indicate successful completion
            all_successful = True
            status_files = list(self.status_file_prefix.parent.glob(f"{self.status_file_prefix.name}*.txt"))
            
            if not status_files:
                logger.info("No status files found - nothing to clean up")
                return
            
            for status_file in status_files:
                try:
                    with open(status_file, 'r') as f:
                        status = f.read().strip()
                    
                    if status not in ["COMPLETED_SUCCESS", "FINISHED"]:
                        all_successful = False
                        logger.warning(f"Task {status_file.name} did not complete successfully (status: {status})")
                        break
                except Exception as e:
                    logger.warning(f"Error reading status file {status_file}: {e}")
                    all_successful = False
                    break
            
            if all_successful:
                logger.info("🎉 All tasks completed successfully! Cleaning up logs directory...")
                
                # Remove individual challenge log files if they exist
                if self.config.enable_logs:
                    log_files = list(self.logs_dir.glob(f"{self.execution_id}_parallel_*.log"))
                    for log_file in log_files:
                        try:
                            log_file.unlink()
                            logger.debug(f"Removed log file: {log_file.name}")
                        except Exception as e:
                            logger.warning(f"Failed to remove log file {log_file}: {e}")
                
                # Remove status files
                for status_file in status_files:
                    try:
                        status_file.unlink()
                        logger.debug(f"Removed status file: {status_file.name}")
                    except Exception as e:
                        logger.warning(f"Failed to remove status file {status_file}: {e}")
                
                # Remove active sessions file if it exists
                if self.active_sessions_file.exists():
                    try:
                        self.active_sessions_file.unlink()
                        logger.debug("Removed active sessions file")
                    except Exception as e:
                        logger.warning(f"Failed to remove active sessions file: {e}")
                
                # Try to remove the logs directory if it's empty
                try:
                    if not any(self.logs_dir.iterdir()):
                        self.logs_dir.rmdir()
                        logger.info("✅ Removed empty logs directory")
                    else:
                        logger.info("📁 Logs directory not empty, keeping it")
                except Exception as e:
                    logger.warning(f"Failed to remove logs directory: {e}")
                
                logger.info("✅ Logs cleanup completed successfully")
            else:
                logger.info("⚠️  Some tasks failed - keeping logs for debugging")
                
        except Exception as e:
            logger.error(f"Error during logs cleanup: {e}")
    
    def cleanup(self) -> None:
        """Clean up all resources"""
        logger.info("🧹 Starting cleanup...")
        
        # Clean up tmux sessions
        self.tmux_manager.cleanup_all_sessions()
        
        # Clean up tracking files
        files_removed = 0
        if self.active_sessions_file.exists():
            self.active_sessions_file.unlink()
            files_removed += 1
        
        # Remove status files for this execution
        for status_file in self.status_file_prefix.parent.glob(f"{self.status_file_prefix.name}*.txt"):
            if status_file.exists():
                status_file.unlink()
                files_removed += 1
        
        if files_removed > 0:
            logger.debug(f"Cleaned up {files_removed} tracking files")
        
        # Clean up Docker resources
        if not self.config.disable_cleanup:
            self.docker_manager.comprehensive_cleanup(self.execution_id)
        
        logger.info("✅ Cleanup completed")
    
    def print_summary(self) -> None:
        """Print execution summary"""
        execution_time = time.time() - self.start_time
        
        # Count results from status files (like bash script)
        successful_jobs = 0
        failed_jobs = 0
        completed_jobs = 0
        
        for status_file in self.status_file_prefix.parent.glob(f"{self.status_file_prefix.name}*.txt"):
            if status_file.exists():
                completed_jobs += 1
                try:
                    with open(status_file, 'r') as f:
                        status = f.read().strip()
                    
                    if status in ["COMPLETED_SUCCESS", "FINISHED"]:
                        successful_jobs += 1
                    elif status == "COMPLETED_FAILED":
                        failed_jobs += 1
                except Exception:
                    pass
        
        logger.info("=" * 50)
        logger.info("🏁 EXECUTION SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Total jobs: {self.total_jobs}")
        logger.info(f"Completed: {completed_jobs}")
        logger.info(f"Successful: {successful_jobs}")
        logger.info(f"Failed: {failed_jobs}")
        logger.info(f"Execution time: {execution_time:.1f}s")
        logger.info(f"Parallel tasks: {self.config.parallel_tasks}")
        
        if failed_jobs == 0:
            logger.info("🎉 All challenges completed successfully!")
        else:
            logger.warning(f"⚠️  {failed_jobs} challenges failed. Check log files in logs/ directory.")

    def cleanup_finished_sessions(self) -> None:
        """Clean up finished sessions based on status files (like bash script)"""
        if not self.active_sessions_file.exists():
            return
        
        # Read current active sessions
        with open(self.active_sessions_file, 'r') as f:
            lines = f.readlines()
        
        # Filter out finished sessions
        active_lines = []
        for line in lines:
            if ':' not in line.strip():
                continue
            
            session_name, status_file = line.strip().split(':', 1)
            
            # Check if session still exists
            try:
                result = subprocess.run([
                    'tmux', 'has-session', '-t', session_name
                ], capture_output=True, text=True)
                
                if result.returncode != 0:
                    logger.debug(f"Session {session_name} no longer exists, removing from tracking")
                    # Update status to failed if session doesn't exist but no status file
                    status_path = Path(status_file)
                    if not status_path.exists():
                        try:
                            status_path.parent.mkdir(exist_ok=True)
                            with open(status_path, 'w') as sf:
                                sf.write("COMPLETED_FAILED")
                            logger.warning(f"Session {session_name} disappeared without status - marking as failed")
                            
                            # Clean up Docker resources for disappeared session
                            if self.config.enable_per_task_cleanup:
                                logger.debug(f"Cleaning up Docker resources for disappeared session: {session_name}")
                                self.docker_manager.cleanup_task_resources(session_name, self.execution_id)
                        except Exception:
                            pass
                    continue
            except Exception:
                continue
            
            # Check status file
            status_path = Path(status_file)
            if status_path.exists():
                try:
                    with open(status_path, 'r') as sf:
                        status = sf.read().strip()
                    
                    if status in ["FINISHED", "COMPLETED_SUCCESS", "COMPLETED_FAILED"]:
                        logger.info(f"Session {session_name} finished with status: {status}")
                        
                        # Kill the tmux session
                        self.tmux_manager.kill_session(session_name)
                        
                        # CRITICAL: Clean up Docker resources for this finished task
                        # This prevents resource exhaustion as tasks complete
                        if self.config.enable_per_task_cleanup:
                            logger.debug(f"Cleaning up Docker resources for finished session: {session_name}")
                            self.docker_manager.cleanup_task_resources(session_name, self.execution_id)
                        else:
                            logger.debug(f"Per-task Docker cleanup disabled - skipping resource cleanup for: {session_name}")
                    else:
                        # Check if session has been running too long (timeout)
                        try:
                            stat = status_path.stat()
                            if time.time() - stat.st_mtime > 3600:  # 1 hour timeout
                                logger.warning(f"Session {session_name} timed out after 1 hour - killing")
                                with open(status_path, 'w') as sf:
                                    sf.write("COMPLETED_FAILED")
                                self.tmux_manager.kill_session(session_name)
                                
                                # Clean up Docker resources for timed out session
                                if self.config.enable_per_task_cleanup:
                                    logger.debug(f"Cleaning up Docker resources for timed out session: {session_name}")
                                    self.docker_manager.cleanup_task_resources(session_name, self.execution_id)
                            else:
                                # Check for Docker errors in log files that might indicate the session is stuck
                                log_file = None
                                if self.config.enable_logs:
                                    # Try to find the corresponding log file
                                    log_pattern = f"{self.execution_id}_parallel_*_{session_name.split('_')[-1]}.log"
                                    log_files = list(self.logs_dir.glob(log_pattern))
                                    if log_files:
                                        log_file = log_files[0]
                                
                                if log_file and log_file.exists():
                                    try:
                                        with open(log_file, 'r') as lf:
                                            log_content = lf.read()
                                        
                                        # Check for Docker errors that indicate the session is stuck
                                        docker_errors = [
                                            "failed to create endpoint.*on network.*exchange full",
                                            "docker.errors.APIError.*500 Server Error",
                                            "failed to create endpoint",
                                            "Internal Server Error",
                                            "docker.errors"
                                        ]
                                        
                                        for error_pattern in docker_errors:
                                            if error_pattern in log_content:
                                                logger.warning(f"Session {session_name} has Docker error in logs - killing")
                                                with open(status_path, 'w') as sf:
                                                    sf.write("COMPLETED_FAILED")
                                                self.tmux_manager.kill_session(session_name)
                                                
                                                # Clean up Docker resources for session with Docker errors
                                                if self.config.enable_per_task_cleanup:
                                                    logger.debug(f"Cleaning up Docker resources for session with Docker errors: {session_name}")
                                                    self.docker_manager.cleanup_task_resources(session_name, self.execution_id)
                                                break
                                        else:
                                            # No Docker errors found, keep session active
                                            active_lines.append(line)
                                    except Exception:
                                        # If we can't read the log file, keep session active
                                        active_lines.append(line)
                                else:
                                    # Keep this session active
                                    active_lines.append(line)
                        except Exception:
                            # Keep session active if we can't check timeout
                            active_lines.append(line)
                except Exception as e:
                    logger.warning(f"Error reading status file {status_file}: {e}")
                    # Keep session active if we can't read status
                    active_lines.append(line)
            else:
                # No status file, check if session exists and has been running too long
                try:
                    result = subprocess.run([
                        'tmux', 'has-session', '-t', session_name
                    ], capture_output=True, text=True)
                    
                    if result.returncode == 0:
                        # Check if session has been running too long without status file
                        # This handles cases where the script fails to start properly
                        session_start_time = time.time() - 300  # Assume 5 minutes ago if no status file
                        if time.time() - session_start_time > 1800:  # 30 minutes timeout for sessions without status
                            logger.warning(f"Session {session_name} has no status file and may be stuck - killing")
                            try:
                                status_path.parent.mkdir(exist_ok=True)
                                with open(status_path, 'w') as sf:
                                    sf.write("COMPLETED_FAILED")
                            except Exception:
                                pass
                            self.tmux_manager.kill_session(session_name)
                            
                            # Clean up Docker resources for stuck session without status
                            if self.config.enable_per_task_cleanup:
                                logger.debug(f"Cleaning up Docker resources for stuck session without status: {session_name}")
                                self.docker_manager.cleanup_task_resources(session_name, self.execution_id)
                        else:
                            active_lines.append(line)
                except Exception:
                    pass
        
        # Write back active sessions (overwrite the file)
        with open(self.active_sessions_file, 'w') as f:
            f.writelines(active_lines)


def parse_arguments() -> Path:
    """Parse command line arguments - only config file path"""
    parser = argparse.ArgumentParser(
        description="Parallel CTF Challenge Runner for SWE-Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default configuration file
  python run_claude_parallel.py
  
  # Run with custom configuration file
  python run_claude_parallel.py --config my_config.yaml
  python run_claude_parallel.py -c my_config.yaml
  
  # Run with configuration file in different location
  python run_claude_parallel.py --config /path/to/config.yaml
        """
    )
    
    parser.add_argument("--config", "-c", type=str, default="parallel_runner_config.yaml",
                       help="Path to configuration YAML file (default: parallel_runner_config.yaml)")
    
    args = parser.parse_args()
    return Path(args.config)


def main():
    """Main entry point"""
    try:
        # Parse arguments to get config file path
        config_path = parse_arguments()
        
        # Load configuration from YAML
        config = RunnerConfig.from_yaml(config_path)
        
        # Validate configuration
        config.validate_configuration()
        
        # Validate environment variables based on model type
        config.validate_environment_variables()
        
        # Create and run the challenge runner
        runner = ChallengeRunner(config)
        
        # Run the challenges
        runner.run_parallel()
        
        # Print summary
        runner.print_summary()
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 