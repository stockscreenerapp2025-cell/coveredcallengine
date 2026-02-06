#!/bin/bash

# setup_vm.sh
# Script to install dependencies and verify prerequisites for CCE deployment.
# Targets Ubuntu/Debian systems. For other systems, it primarily verifies.

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting CCE Setup Script...${NC}"

OS_NAME=$(uname -s)
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$NAME
else
    DISTRO="Unknown"
fi

echo -e "Detected OS: $OS_NAME ($DISTRO)"

is_ubuntu() {
    [[ "$DISTRO" == *"Ubuntu"* ]] || [[ "$DISTRO" == *"Debian"* ]]
}

install_packages_ubuntu() {
    echo -e "${YELLOW}Updating package lists...${NC}"
    sudo apt-get update -y

    echo -e "${YELLOW}Installing basic tools (curl, git, software-properties-common)...${NC}"
    sudo apt-get install -y curl git software-properties-common build-essential

    # 1. Install Python 3.12
    if ! command -v python3.12 &> /dev/null; then
        echo -e "${YELLOW}Installing Python 3.12...${NC}"
        sudo add-apt-repository ppa:deadsnakes/ppa -y
        sudo apt-get update -y
        sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
    else
        echo -e "${GREEN}Python 3.12 is already installed.${NC}"
    fi

    # 2. Install Node.js (Latest Stable - Setup NodeSource)
    #if ! command -v node &> /dev/null; then
    #    echo -e "${YELLOW}Installing Node.js (Latest Stable)...${NC}"
    #    curl -fsSL https://deb.nodesource.com/setup_current.x | sudo -E bash -
    #    sudo apt-get install -y nodejs
    #else
    #    echo -e "${GREEN}Node.js is already installed: $(node -v)${NC}"
    #fi

    # 3. Install Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${YELLOW}Installing Docker...${NC}"
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        rm get-docker.sh
        sudo usermod -aG docker $USER
        echo -e "${YELLOW}Added current user to docker group. You may need to re-login.${NC}"
    else
        echo -e "${GREEN}Docker is already installed.${NC}"
    fi

    # 4. Install Docker Compose (if not part of docker cli)
    if ! docker compose version &> /dev/null; then
        echo -e "${YELLOW}Installing Docker Compose Plugin...${NC}"
        sudo apt-get install -y docker-compose-plugin
    else
         echo -e "${GREEN}Docker Compose is already installed.${NC}"
    fi

    # # 5. Configure Firewall (UFW)
    # if command -v ufw &> /dev/null; then
    #     echo -e "${YELLOW}Configuring Firewall (UFW)...${NC}"
    #     sudo ufw allow 80/tcp
    #     sudo ufw allow 443/tcp
    #     sudo ufw allow 22/tcp
    #     echo "y" | sudo ufw enable
    # fi

    # 6. Ensure scripts are executable
    chmod +x init_letsencrypt.sh deploy.sh init_dirs.sh
}

verify_prerequisites() {
    echo -e "\n${YELLOW}=== Verifying Prerequisites ===${NC}"
    
    # Python
    if command -v python3.12 &> /dev/null; then
        echo -e "${GREEN}✅ Python 3.12 found.$(python3.12 --version)${NC}"
    else
        echo -e "${RED}❌ Python 3.12 NOT found.${NC}"
    fi

    # Node
    if command -v node &> /dev/null; then
        echo -e "${GREEN}✅ Node.js found: $(node -v)${NC}"
    else
        echo -e "${RED}❌ Node.js NOT found.${NC}"
    fi

    # Docker
    if command -v docker &> /dev/null; then
        echo -e "${GREEN}✅ Docker found: $(docker --version)${NC}"
    else
        echo -e "${RED}❌ Docker NOT found.${NC}"
    fi

    # Docker Compose
    if docker compose version &> /dev/null; then
        echo -e "${GREEN}✅ Docker Compose found.${NC}"
    else
        echo -e "${RED}❌ Docker Compose NOT found.${NC}"
    fi
}

if is_ubuntu; then
    echo -e "${GREEN}Running on Ubuntu/Debian. Attempting automatic installation...${NC}"
    install_packages_ubuntu
else
    echo -e "${YELLOW}Not running on Ubuntu/Debian. Skipping automatic installation.${NC}"
    echo "Please manually ensure requirements are met."
fi

verify_prerequisites

echo -e "\n${GREEN}Setup script completed.${NC}"
