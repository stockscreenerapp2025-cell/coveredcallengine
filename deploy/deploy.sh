#!/bin/bash

# deploy.sh
# Orchestrates the deployment of CCE application

set -e

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}Starting Deployment...${NC}"

# 1. Pull Latest Code
#echo -e "${GREEN}Pulling latest code...${NC}"
#git pull origin main

# 2. Initialize directories
#echo "Running init_dirs.sh..."
#bash ./init_dirs.sh

# 3. Create MongoDB volume if it doesn't exist (for data persistence)
echo -e "${GREEN}Ensuring MongoDB volume exists...${NC}"
docker volume create cce_mongo_data 2>/dev/null || true

# 4. Build and Start Docker Containers
echo -e "${GREEN}Building and starting containers...${NC}"
# Setup for production usually involves using the prod compose file if available, 
# relying on the user's setup. The plan mentioned docker-compose.prod.yml.
# Checking if it exists in the directory first is good practice, but I will assume standard usage based on file list.
if [ -f "docker-compose.prod.yml" ]; then
    COMPOSE_FILE="docker-compose.prod.yml"
else
    COMPOSE_FILE="docker-compose.yml"
fi

echo "Using compose file: $COMPOSE_FILE"
docker compose -f $COMPOSE_FILE up -d --build

# 4. Prune unused images to save space
echo -e "${GREEN}Pruning unused images...${NC}"
docker image prune -f

echo -e "${GREEN}Deployment Successful!${NC}"
echo -e "Frontend: http://localhost:3000"
echo -e "Backend:  http://localhost:8000/docs"
