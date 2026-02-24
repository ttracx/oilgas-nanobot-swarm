#!/bin/bash
# Launch vLLM server optimized for RTX 4060 Ti 16GB + WSL2
set -e

source ~/vllm-nanobot-env/bin/activate

# WSL2 fix
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export CUDA_VISIBLE_DEVICES=0

MODEL="TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill"
HOST="0.0.0.0"
PORT="8000"

# Generate API key if not exists
if [ ! -f ~/.nanobot_api_key ]; then
    API_KEY="nq-nanobot-$(openssl rand -hex 16)"
    echo "$API_KEY" > ~/.nanobot_api_key
    echo "Generated API key: $API_KEY"
else
    API_KEY=$(cat ~/.nanobot_api_key)
    echo "Using existing API key"
fi

echo "Launching vLLM server on :${PORT}..."
echo "Model: $MODEL"

python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --host "$HOST" \
    --port "$PORT" \
    --api-key "$API_KEY" \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.85 \
    --max-model-len 8192 \
    --max-num-seqs 32 \
    --max-num-batched-tokens 16384 \
    --tensor-parallel-size 1 \
    --enable-chunked-prefill \
    --disable-log-requests \
    --served-model-name "nanobot-reasoner" \
    --trust-remote-code \
    2>&1 | tee ~/vllm_server.log
