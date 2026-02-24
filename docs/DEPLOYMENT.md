# Deployment Guide

## Prerequisites

- Linux or WSL2 (Ubuntu 22.04+)
- NVIDIA GPU with 12+ GB VRAM
- NVIDIA driver 525+ with CUDA 12.0+
- Python 3.11 or 3.12
- Redis 7.0+
- [uv](https://github.com/astral-sh/uv) package manager (recommended)

## Step 1: Clone and Setup Environment

```bash
git clone https://github.com/ttracx/nanobot-swarm.git
cd nanobot-swarm

# Create virtual environment
uv venv ~/vllm-nanobot-env --python 3.12
source ~/vllm-nanobot-env/bin/activate

# Install the package + dependencies
uv pip install -e .

# Install PyTorch + vLLM (CUDA)
uv pip install torch vllm
```

## Step 2: Verify GPU

```bash
# WSL2
/usr/lib/wsl/lib/nvidia-smi

# Native Linux
nvidia-smi

# Verify PyTorch sees GPU
python3 -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## Step 3: Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
VLLM_URL=http://localhost:8000/v1
VLLM_API_KEY=your-secure-key
GATEWAY_API_KEY=your-gateway-key
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password
REDIS_DB=0
```

## Step 4: Launch

### Option A: All-in-one (recommended)

```bash
bash scripts/start_all.sh
```

This launches Redis, vLLM (waits for model to load), then the Gateway.

### Option B: Individual components

**Terminal 1 — Redis:**
```bash
bash scripts/launch_redis.sh
```

**Terminal 2 — vLLM:**
```bash
bash scripts/launch_vllm.sh
```

Wait for `INFO: Application startup complete` in the vLLM log.

**Terminal 3 — Gateway:**
```bash
bash scripts/launch_gateway.sh
```

## Step 5: Verify

```bash
# Health check
curl http://localhost:8100/health

# Topology
curl -H "x-api-key: nq-gateway-key" http://localhost:8100/swarm/topology

# Test run
curl -X POST http://localhost:8100/swarm/run \
  -H "Content-Type: application/json" \
  -H "x-api-key: nq-gateway-key" \
  -d '{"goal": "Explain the difference between REST and GraphQL in 3 paragraphs"}'
```

## vLLM Configuration

The launch script is optimized for RTX 4060 Ti 16GB. Adjust for other GPUs:

| Parameter | RTX 4060 Ti 16GB | RTX 3090 24GB | A100 40GB |
|-----------|------------------|---------------|-----------|
| `--dtype` | bfloat16 | bfloat16 | bfloat16 |
| `--gpu-memory-utilization` | 0.85 | 0.90 | 0.90 |
| `--max-model-len` | 8192 | 16384 | 32768 |
| `--max-num-seqs` | 32 | 64 | 128 |
| `--max-num-batched-tokens` | 16384 | 32768 | 65536 |

Edit `scripts/launch_vllm.sh` to change these.

## Redis Configuration

The Redis config at `/etc/redis/redis-nanobot.conf` reserves up to 32GB RAM for state. Key settings:

- `maxmemory 32gb` — Adjust based on available RAM
- `appendonly yes` — AOF persistence for crash recovery
- `maxmemory-policy allkeys-lru` — Evict old data under memory pressure

## Systemd Service (Production)

Create `/etc/systemd/system/nanobot-vllm.service`:

```ini
[Unit]
Description=NeuralQuantum vLLM Nanobot Server
After=network.target redis.service

[Service]
Type=simple
User=ttracx
WorkingDirectory=/home/ttracx/nanobot-swarm
ExecStart=/bin/bash /home/ttracx/nanobot-swarm/scripts/launch_vllm.sh
Restart=always
RestartSec=10
Environment=CUDA_VISIBLE_DEVICES=0

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/nanobot-gateway.service`:

```ini
[Unit]
Description=NeuralQuantum Nanobot Gateway
After=network.target nanobot-vllm.service redis.service

[Service]
Type=simple
User=ttracx
WorkingDirectory=/home/ttracx/nanobot-swarm
ExecStart=/bin/bash /home/ttracx/nanobot-swarm/scripts/launch_gateway.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable nanobot-vllm nanobot-gateway
sudo systemctl start nanobot-vllm nanobot-gateway
```

## Monitoring

### Logs

```bash
tail -f ~/vllm_server.log        # vLLM inference
tail -f ~/nanobot_gateway.log    # Gateway API
sudo tail -f /var/log/redis/nanobot-redis.log  # Redis
```

### Health endpoints

```bash
# System health
curl http://localhost:8100/health

# Swarm health (agents, sessions, Redis memory)
curl -H "x-api-key: nq-gateway-key" http://localhost:8100/swarm/health

# Active agents
curl -H "x-api-key: nq-gateway-key" http://localhost:8100/agents
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| vLLM OOM | Reduce `--gpu-memory-utilization` or `--max-model-len` |
| Slow first request | Model loads on first request; wait ~60-90s |
| Redis connection refused | Run `bash scripts/launch_redis.sh` |
| Tool calls not working | Model may not support function calling natively; the router falls back to text mode |
| WSL2 CUDA not found | Ensure `nvidia-smi` works at `/usr/lib/wsl/lib/nvidia-smi` |
