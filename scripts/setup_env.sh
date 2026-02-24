#!/bin/bash
# NeuralQuantum vLLM Nanobot Deployment Setup
# Run inside WSL2 Ubuntu
set -e

echo "=== NeuralQuantum vLLM Nanobot Deployment Setup ==="

# Verify CUDA visibility in WSL2
/usr/lib/wsl/lib/nvidia-smi || { echo "ERROR: CUDA not visible in WSL2."; exit 1; }

# Python venv
echo "Creating Python virtual environment..."
python3 -m venv ~/vllm-nanobot-env
source ~/vllm-nanobot-env/bin/activate

# Install vLLM + dependencies
pip install --upgrade pip
pip install vllm torch

# Install nanobot-swarm package
cd ~/nanobot-swarm
pip install -e .

# Create workspace directory
mkdir -p ~/nanobot_workspace

echo "=== Setup complete ==="
echo "Activate with: source ~/vllm-nanobot-env/bin/activate"
