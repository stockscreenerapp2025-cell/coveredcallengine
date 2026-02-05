#!/bin/bash

# deploy_local_mac.sh
# Single script to deploy CCE locally on macOS
# Checks prerequisites, initializes directories, and runs Docker Compose

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}Starting CCE Local Mac Deployment...${NC}"

# 1. OS Check
OS_NAME=$(uname -s)
if [ "$OS_NAME" != "Darwin" ]; then
    echo -e "${RED}Error: This script is intended for macOS. Detected: $OS_NAME${NC}"
    exit 1
fi

# 2. Check for Docker
echo -e "${YELLOW}Checking Prerequisites...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed.${NC}"
    echo -e "Please install Docker Desktop for Mac: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}Docker daemon is not running.${NC}"
    echo -e "Please start Docker Desktop and try again."
    exit 1
fi

echo -e "${GREEN}✅ Docker is running.${NC}"

# 3. Initialize Directories
echo -e "\n${YELLOW}Initializing Directories...${NC}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
bash "$SCRIPT_DIR/init_dirs.sh"

# 4. Run Docker Compose
echo -e "\n${YELLOW}Building and Starting Containers...${NC}"
# Use the docker-compose.yml from the same directory
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d --build

echo -e "\n${GREEN}Deployment Successful!${NC}"
echo -e "Frontend: http://localhost:3000"
echo -e "Backend:  http://localhost:8000/docs"
echo -e "\nTo stop the application, run:"
echo -e "  cd deploy && docker compose down"
