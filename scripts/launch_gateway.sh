#!/bin/bash
# Launch the Nanobot Swarm Gateway API
set -e

source ~/vllm-nanobot-env/bin/activate

API_KEY=$(cat ~/.nanobot_api_key 2>/dev/null || echo "nq-nanobot")

export VLLM_API_KEY="$API_KEY"
export VLLM_URL="http://localhost:8000/v1"
export GATEWAY_API_KEY="nq-gateway-key"
export REDIS_HOST="127.0.0.1"
export REDIS_PORT="6379"
export REDIS_PASSWORD="nq-redis-nanobot-2025"

echo "Launching Nanobot Swarm Gateway on :8100..."
echo "vLLM:    $VLLM_URL"
echo "Redis:   $REDIS_HOST:$REDIS_PORT"
echo "Docs:    http://localhost:8100/docs"

cd ~/nanobot-swarm

uvicorn nanobot.api.gateway:app \
    --host 0.0.0.0 \
    --port 8100 \
    --workers 1 \
    --log-level info \
    2>&1 | tee ~/nanobot_gateway.log
