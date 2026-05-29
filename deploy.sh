#!/bin/bash
set -e

echo '[deploy] pulling latest...'
cd /opt/furniture-generator

# Ensure SOCKS proxy tunnel is running
if ! ss -tlnp | grep -q 2080; then
    echo '[deploy] starting proxy tunnel...'
    nohup ssh -N -D 127.0.0.1:2080 -o ServerAliveInterval=60 -o ExitOnForwardFailure=yes root@43.155.195.27 > /dev/null 2>&1 &
    sleep 2
fi

git pull origin main

echo '[deploy] installing files...'
cp index.html /var/www/poster-studio/furniture.html

sed -e "s|_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))|_load_dotenv('/etc/furniture-generator.env')|" \
    -e "s|UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')|UPLOAD_DIR = '/var/www/poster-studio/uploads'|" \
    api.py > /usr/local/bin/furniture_api.py

echo '[deploy] restarting service...'
systemctl restart furniture-generator.service

sleep 2
curl -s http://127.0.0.1:8893/api/health || echo 'health check failed'
echo ''
echo '[deploy] done.'
