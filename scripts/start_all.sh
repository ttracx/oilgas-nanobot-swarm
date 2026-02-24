#!/bin/bash
# Start the complete Nanobot Swarm System
# 1. Redis (state layer)
# 2. vLLM (inference server)
# 3. Gateway API (HTTP interface)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== NeuralQuantum Nanobot Swarm System ==="
echo ""

# 1. Redis
echo "[1/3] Starting Redis..."
bash "$SCRIPT_DIR/launch_redis.sh"
echo ""

# 2. vLLM (background)
echo "[2/3] Starting vLLM server..."
nohup bash "$SCRIPT_DIR/launch_vllm.sh" > ~/vllm_server.log 2>&1 &
VLLM_PID=$!
echo "vLLM PID: $VLLM_PID"

echo "Waiting for vLLM to be ready (model loading ~60-90s)..."
MAX_WAIT=180
WAITED=0
while ! curl -s http://localhost:8000/health > /dev/null 2>&1; do
    sleep 5
    WAITED=$((WAITED + 5))
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "ERROR: vLLM did not start within ${MAX_WAIT}s"
        echo "Check logs: tail -f ~/vllm_server.log"
        exit 1
    fi
    echo "  ...waiting ($WAITED/${MAX_WAIT}s)"
done
echo "vLLM ready!"
echo ""

# 3. Gateway
echo "[3/3] Starting Gateway API..."
nohup bash "$SCRIPT_DIR/launch_gateway.sh" > ~/nanobot_gateway.log 2>&1 &
GW_PID=$!

sleep 3
echo ""
echo "=== Nanobot Swarm System Running ==="
echo "  vLLM:    http://localhost:8000  (PID: $VLLM_PID)"
echo "  Gateway: http://localhost:8100  (PID: $GW_PID)"
echo "  Docs:    http://localhost:8100/docs"
echo "  Redis:   localhost:6379"
echo ""
echo "Test with:"
echo '  curl -X POST http://localhost:8100/swarm/run \'
echo '    -H "Content-Type: application/json" \'
echo '    -H "x-api-key: nq-gateway-key" \'
echo '    -d '"'"'{"goal": "Explain quantum computing in 3 paragraphs"}'"'"''
