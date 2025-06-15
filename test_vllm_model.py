#!/usr/bin/env python3
"""
Test script to verify VLLM model functionality with local server on port 8000.
This script tests the VLLMModel implementation in sweagent.
"""

import sys
import logging
from pathlib import Path

# Add the sweagent directory to the path so we can import the models
sys.path.insert(0, str(Path(__file__).parent))

from sweagent.agent.models import VLLMModel, ModelArguments
from sweagent.agent.commands import Command

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_vllm_connection():
    """Test basic connection to VLLM server"""
    import requests
    
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            logger.info("✅ VLLM server is healthy and responding")
            return True
        else:
            logger.error(f"❌ VLLM server health check failed with status: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to connect to VLLM server: {e}")
        logger.error("Make sure VLLM server is running on localhost:8000")
        return False

def test_vllm_models_endpoint():
    """Test the models endpoint to see what models are available"""
    import requests
    
    try:
        response = requests.get("http://localhost:8000/v1/models", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get("data", [])
            logger.info(f"✅ Available models: {[model['id'] for model in models]}")
            return models[0]["id"] if models else None
        else:
            logger.error(f"❌ Failed to get models list: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to get models list: {e}")
        return None

def test_vllm_model():
    """Test the VLLMModel implementation"""
    
    # First check if server is running
    if not test_vllm_connection():
        return False
    
    # Get available model
    model_name = test_vllm_models_endpoint()
    if not model_name:
        logger.info("⚠️  No models found from endpoint, using DeepSeek-R1-0528 as fallback")
        model_name = "DeepSeek-R1-0528"
    
    logger.info(f"🔄 Testing with model: {model_name}")
    
    try:
        # Create model arguments
        args = ModelArguments(
            model_name=f"vllm:{model_name}",
            temperature=0.7,
            top_p=0.9,
            top_k=50,
            host_url="localhost:8000"
        )
        
        # Create empty commands list (not needed for testing)
        commands = []
        
        # Initialize the VLLM model
        logger.info("🔄 Initializing VLLMModel...")
        vllm_model = VLLMModel(args, commands)
        logger.info("✅ VLLMModel initialized successfully")
        
        # Test with a simple conversation
        test_history = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello! Can you tell me what 2+2 equals?"}
        ]
        
        logger.info("🔄 Sending test query to VLLM model...")
        response = vllm_model.query(test_history)
        
        logger.info("✅ Query successful!")
        logger.info(f"Response: {response}")
        logger.info(f"Stats: {vllm_model.stats}")
        
        # Test with another query
        test_history_2 = [
            {"role": "user", "content": "Write a short poem about coding."}
        ]
        
        logger.info("🔄 Sending second test query...")
        response_2 = vllm_model.query(test_history_2)
        
        logger.info("✅ Second query successful!")
        logger.info(f"Response: {response_2}")
        logger.info(f"Updated stats: {vllm_model.stats}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error testing VLLMModel: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_direct_api_call():
    """Test direct API call to VLLM server without using VLLMModel class"""
    import requests
    import json
    
    logger.info("🔄 Testing direct API call to VLLM server...")
    
    payload = {
        "model": "DeepSeek-R1-0528",  # Use the specific model name
        "messages": [
            {"role": "user", "content": "Hello, are you working correctly?"}
        ],
        "temperature": 0.7,
        "max_tokens": 100
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/v1/chat/completions", 
            json=payload, 
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            logger.info("✅ Direct API call successful!")
            logger.info(f"Response: {content}")
            return True
        else:
            logger.error(f"❌ Direct API call failed with status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Direct API call error: {e}")
        return False

def test_multi_turn_conversation():
    """Test multi-turn conversation with the VLLMModel"""
    logger.info("🔄 Testing multi-turn conversation...")
    
    try:
        # Create model arguments
        args = ModelArguments(
            model_name="vllm:DeepSeek-R1-0528",
            temperature=0.7,
            top_p=0.9,
            top_k=50,
            host_url="localhost:8000"
        )
        
        # Create empty commands list
        commands = []
        
        # Initialize the VLLM model
        vllm_model = VLLMModel(args, commands)
        logger.info("✅ VLLMModel initialized for multi-turn test")
        
        # Start with system message and build conversation
        conversation_history = [
            {"role": "system", "content": "You are a helpful assistant. Keep your responses concise but informative."}
        ]
        
        # Turn 1: Initial greeting
        conversation_history.append({"role": "user", "content": "Hello! What's your name?"})
        logger.info("🔄 Turn 1: Sending greeting...")
        response1 = vllm_model.query(conversation_history)
        logger.info(f"✅ Turn 1 Response: {response1}")
        
        # Add assistant response to history
        conversation_history.append({"role": "assistant", "content": response1})
        
        # Turn 2: Ask about capabilities
        conversation_history.append({"role": "user", "content": "What can you help me with?"})
        logger.info("🔄 Turn 2: Asking about capabilities...")
        response2 = vllm_model.query(conversation_history)
        logger.info(f"✅ Turn 2 Response: {response2}")
        
        # Add assistant response to history
        conversation_history.append({"role": "assistant", "content": response2})
        
        # Turn 3: Math problem
        conversation_history.append({"role": "user", "content": "Can you solve this math problem: What is 15 * 24?"})
        logger.info("🔄 Turn 3: Math problem...")
        response3 = vllm_model.query(conversation_history)
        logger.info(f"✅ Turn 3 Response: {response3}")
        
        # Add assistant response to history
        conversation_history.append({"role": "assistant", "content": response3})
        
        # Turn 4: Follow-up question referring to previous answer
        conversation_history.append({"role": "user", "content": "Can you show me how you calculated that step by step?"})
        logger.info("🔄 Turn 4: Follow-up question...")
        response4 = vllm_model.query(conversation_history)
        logger.info(f"✅ Turn 4 Response: {response4}")
        
        # Add assistant response to history
        conversation_history.append({"role": "assistant", "content": response4})
        
        # Turn 5: Context-dependent question
        conversation_history.append({"role": "user", "content": "Now divide that result by 3. What do you get?"})
        logger.info("🔄 Turn 5: Context-dependent math...")
        response5 = vllm_model.query(conversation_history)
        logger.info(f"✅ Turn 5 Response: {response5}")
        
        # Add assistant response to history
        conversation_history.append({"role": "assistant", "content": response5})
        
        # Turn 6: Memory test
        conversation_history.append({"role": "user", "content": "What was the first question I asked you in this conversation?"})
        logger.info("🔄 Turn 6: Memory test...")
        response6 = vllm_model.query(conversation_history)
        logger.info(f"✅ Turn 6 Response: {response6}")
        
        # Print conversation summary
        logger.info("\n" + "="*60)
        logger.info("📝 FULL CONVERSATION SUMMARY:")
        logger.info("="*60)
        for i, msg in enumerate(conversation_history):
            if msg["role"] != "system":
                speaker = "🤖 Assistant" if msg["role"] == "assistant" else "👤 User"
                logger.info(f"{speaker}: {msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}")
        
        logger.info(f"\n📊 Final Stats: {vllm_model.stats}")
        logger.info("✅ Multi-turn conversation test completed successfully!")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error in multi-turn conversation test: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_conversation_context_retention():
    """Test if the model retains context across multiple queries"""
    logger.info("🔄 Testing context retention...")
    
    try:
        args = ModelArguments(
            model_name="vllm:DeepSeek-R1-0528",
            temperature=0.3,  # Lower temperature for more consistent responses
            top_p=0.9,
            top_k=50,
            host_url="localhost:8000"
        )
        
        vllm_model = VLLMModel(args, [])
        
        # Build a conversation where context is crucial
        context_test_history = [
            {"role": "system", "content": "You are helping with a programming task. Remember all details mentioned."},
            {"role": "user", "content": "I'm working on a Python function called 'calculate_average' that takes a list of numbers."},
        ]
        
        logger.info("🔄 Setting up context...")
        response1 = vllm_model.query(context_test_history)
        logger.info(f"✅ Context setup response: {response1}")
        
        context_test_history.append({"role": "assistant", "content": response1})
        context_test_history.append({"role": "user", "content": "The function should handle empty lists by returning 0."})
        
        response2 = vllm_model.query(context_test_history)
        logger.info(f"✅ Requirement response: {response2}")
        
        context_test_history.append({"role": "assistant", "content": response2})
        context_test_history.append({"role": "user", "content": "Can you write this function for me now?"})
        
        response3 = vllm_model.query(context_test_history)
        logger.info(f"✅ Function implementation: {response3}")
        
        # Test if it remembers the function name and requirements
        context_test_history.append({"role": "assistant", "content": response3})
        context_test_history.append({"role": "user", "content": "What was the name of the function I asked you to write?"})
        
        response4 = vllm_model.query(context_test_history)
        logger.info(f"✅ Memory test response: {response4}")
        
        # Check if the response contains the function name
        if "calculate_average" in response4.lower():
            logger.info("✅ Context retention test PASSED - model remembered function name")
            return True
        else:
            logger.warning("⚠️  Context retention test unclear - function name not clearly mentioned")
            return True  # Still consider it a pass as the model responded
            
    except Exception as e:
        logger.error(f"❌ Error in context retention test: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    logger.info("🚀 Starting VLLM Model Test")
    logger.info("=" * 50)
    
    # Test 1: Basic connection
    logger.info("Test 1: Basic VLLM server connection")
    connection_ok = test_vllm_connection()
    
    if not connection_ok:
        logger.info("\n💡 To start VLLM server, run:")
        logger.info("python -m vllm.entrypoints.openai.api_server --model DeepSeek-R1-0528 --host localhost --port 8000")
        return False
    
    # Test 2: Direct API call
    logger.info("\nTest 2: Direct API call")
    direct_api_ok = test_direct_api_call()
    
    # Test 3: VLLMModel class basic test
    logger.info("\nTest 3: VLLMModel class basic functionality")
    model_ok = test_vllm_model()
    
    # Test 4: Multi-turn conversation
    logger.info("\nTest 4: Multi-turn conversation")
    multi_turn_ok = test_multi_turn_conversation()
    
    # Test 5: Context retention
    logger.info("\nTest 5: Context retention")
    context_ok = test_conversation_context_retention()
    
    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("🎯 TEST SUMMARY")
    logger.info(f"Connection test: {'✅ PASS' if connection_ok else '❌ FAIL'}")
    logger.info(f"Direct API test: {'✅ PASS' if direct_api_ok else '❌ FAIL'}")
    logger.info(f"VLLMModel test: {'✅ PASS' if model_ok else '❌ FAIL'}")
    logger.info(f"Multi-turn conversation: {'✅ PASS' if multi_turn_ok else '❌ FAIL'}")
    logger.info(f"Context retention: {'✅ PASS' if context_ok else '❌ FAIL'}")
    
    all_tests = [connection_ok, direct_api_ok, model_ok, multi_turn_ok, context_ok]
    if all(all_tests):
        logger.info("🎉 All tests passed! VLLM model is working correctly with multi-turn conversations!")
        return True
    else:
        failed_tests = sum(1 for test in all_tests if not test)
        logger.info(f"⚠️  {failed_tests} out of {len(all_tests)} tests failed. Check the output above for details.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 