sudo chown -R 100:101 ./data
sudo find ./data -type d -exec chmod 750 {} \;
sudo find ./data -type f -exec chmod 640 {} \;

docker compose restart app
docker compose exec app ls -la /app/data/snapshots