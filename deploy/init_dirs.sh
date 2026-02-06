#!/bin/bash

# init_dirs.sh
# Creates necessary directories for deployment

set -e

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}Creating deployment directories...${NC}"

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Create MongoDB data directory (Used for host-mounted volume persistence)
echo "Creating mongo_data for MongoDB persistence..."
mkdir -p "$DEPLOY_ROOT/mongo_data"

# Create Logs directory
echo "Creating logs..."
mkdir -p "$DEPLOY_ROOT/logs"

# Set permissions for host-mounted volumes (MongoDB runs as UID 999)
chmod 777 "$DEPLOY_ROOT/mongo_data"
chmod 777 "$DEPLOY_ROOT/logs"

echo -e "${GREEN}Directories created successfully.${NC}"
ls -ld "$DEPLOY_ROOT/mongo_data" "$DEPLOY_ROOT/logs"
