#!/bin/bash
set -e

echo '[deploy] pulling latest...'
cd /opt/furniture-generator
git pull origin main

echo '[deploy] installing files...'
cp index.html /var/www/poster-studio/furniture.html

# Adjust paths for VPS environment and deploy
sed -e "s|_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))|_load_dotenv('/etc/furniture-generator.env')|" \
    -e "s|UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')|UPLOAD_DIR = '/var/www/poster-studio/uploads'|" \
    api.py > /usr/local/bin/furniture_api.py

echo '[deploy] restarting service...'
systemctl restart furniture-generator.service

sleep 2
curl -s http://127.0.0.1:8893/api/health
echo ''
echo '[deploy] done.'
