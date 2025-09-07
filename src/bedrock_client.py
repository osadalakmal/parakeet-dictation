#!/usr/bin/env python3
import boto3
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class BedrockClient:
    def __init__(self):
        """Initialize Bedrock runtime client"""
        self.region_name = os.getenv('AWS_REGION', 'us-east-1')
        self.model_id = os.getenv('BEDROCK_MODEL_ID', 'anthropic.claude-3-haiku-20240307-v1:0')
        
        # Initialize boto3 client for Bedrock Runtime
        try:
            self.client = boto3.client(
                'bedrock-runtime',
                region_name=self.region_name,
            )
            print(f"Bedrock client initialized with model: {self.model_id}")
        except Exception as e:
            print(f"Error initializing Bedrock client: {e}")
            self.client = None
    
    def enhance_text(self, transcribed_text, selected_text):
        """
        Send transcribed instruction and selected text to Claude via Bedrock.
        Returns the enhanced/modified text.
        """
        if not self.client:
            raise Exception("Bedrock client not initialized")
        
        # Construct the prompt for Claude
        prompt = f"""You are helping a user edit text based on voice commands. The user has selected some text and given a voice instruction for how to modify it.

Selected text: "{selected_text}"
Voice instruction: "{transcribed_text}"

Please modify the selected text according to the voice instruction. Return only the modified text without any explanation or additional formatting."""
        
        # Prepare the request body for Anthropic Claude
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }
        
        try:
            # Invoke the model
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
                contentType='application/json',
                accept='application/json'
            )
            
            # Parse the response
            response_body = json.loads(response['body'].read().decode('utf-8'))
            
            # Extract the generated text
            if 'content' in response_body and len(response_body['content']) > 0:
                enhanced_text = response_body['content'][0]['text'].strip()
                print(f"Bedrock response: {enhanced_text}")
                return enhanced_text
            else:
                raise Exception("No content in Bedrock response")
                
        except Exception as e:
            print(f"Error calling Bedrock: {e}")
            raise
    
    def test_connection(self):
        """Test if Bedrock client is working properly"""
        if not self.client:
            return False, "Client not initialized"
        
        try:
            # Simple test with a basic prompt
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 50,
                "messages": [
                    {
                        "role": "user",
                        "content": "Say 'Hello, Bedrock connection successful!'"
                    }
                ]
            }
            
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
                contentType='application/json',
                accept='application/json'
            )
            
            response_body = json.loads(response['body'].read().decode('utf-8'))
            
            if 'content' in response_body and len(response_body['content']) > 0:
                return True, response_body['content'][0]['text'].strip()
            else:
                return False, "No content in response"
                
        except Exception as e:
            return False, str(e)
    
    def is_available(self):
        """Check if Bedrock client is available and configured"""
        return self.client is not None
    
    def get_model_info(self):
        """Get information about the current model configuration"""
        return {
            'model_id': self.model_id,
            'region': self.region_name,
            'available': self.is_available()
        }