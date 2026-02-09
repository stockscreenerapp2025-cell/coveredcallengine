#!/bin/bash

# deploy_local_windows.sh
# Script to deploy CCE locally on Windows (using Git Bash or WSL)
# Checks prerequisites, initializes directories, and runs Docker Compose

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}Starting CCE Local Windows Deployment...${NC}"

# 1. OS Check (Minimal check for Windows-like environments in bash)
OS_NAME=$(uname -s)
if [[ "$OS_NAME" != *"NT"* && "$OS_NAME" != *"MINGW"* && "$OS_NAME" != *"CYGWIN"* && "$OS_NAME" != *"Linux"* ]]; then
    echo -e "${YELLOW}Warning: This script is intended for Windows (Git Bash/WSL). Detected: $OS_NAME${NC}"
    echo -e "Proceeding anyway... if this is a Mac, please use deploy_local_mac.sh"
fi

# 2. Check for Docker
echo -e "${YELLOW}Checking Prerequisites...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed.${NC}"
    echo -e "Please install Docker Desktop for Windows: https://www.docker.com/products/docker-desktop/"
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
# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Reference scripts in the parent 'deploy' directory
bash "$SCRIPT_DIR/../init_dirs.sh"

# 4. Run Docker Compose
echo -e "\n${YELLOW}Building and Starting Containers...${NC}"
# Use the docker-compose.yml from the parent directory
docker compose -f "$SCRIPT_DIR/../docker-compose.yml" up -d --build

echo -e "\n${GREEN}Deployment Successful!${NC}"
echo -e "Frontend: http://localhost:3000"
echo -e "Backend:  http://localhost:8000/docs"
echo -e "\nTo stop the application, run:"
echo -e "  cd deploy && docker compose down"
