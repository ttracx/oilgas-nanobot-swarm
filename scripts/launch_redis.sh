#!/bin/bash
# Launch Redis for nanobot state layer
set -e

REDIS_DIR=/var/lib/redis/nanobot
LOG_DIR=/var/log/redis

# Create directories
sudo mkdir -p "$REDIS_DIR" "$LOG_DIR"
sudo chown redis:redis "$REDIS_DIR" "$LOG_DIR" 2>/dev/null || true

# Check if Redis is already running on port 6379
if redis-cli -a nq-redis-nanobot-2025 ping 2>/dev/null | grep -q PONG; then
    echo "Redis is already running"
    exit 0
fi

# Check if config exists, create if not
REDIS_CONF=/etc/redis/redis-nanobot.conf
if [ ! -f "$REDIS_CONF" ]; then
    echo "Creating Redis config at $REDIS_CONF..."
    sudo tee "$REDIS_CONF" > /dev/null << 'CONF'
bind 127.0.0.1
port 6379
protected-mode yes
requirepass nq-redis-nanobot-2025

maxmemory 32gb
maxmemory-policy allkeys-lru
activerehashing yes

appendonly yes
appendfsync everysec
dir /var/lib/redis/nanobot/

save 900 1
save 300 10
save 60 10000

tcp-backlog 511
hz 20
lazyfree-lazy-eviction yes
lazyfree-lazy-expire yes

loglevel notice
logfile /var/log/redis/nanobot-redis.log
CONF
fi

# Launch
sudo redis-server "$REDIS_CONF" --daemonize yes

sleep 2
redis-cli -a nq-redis-nanobot-2025 ping && echo "Redis is UP"
