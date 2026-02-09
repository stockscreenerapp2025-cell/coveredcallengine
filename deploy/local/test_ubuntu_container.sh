#!/bin/bash

# test_ubuntu_container.sh
# Script to create an Ubuntu container for testing CCE deployment

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

CONTAINER_NAME="cce-test-ubuntu"
CCE_SOURCE="/Users/vinayakmalviya/Downloads/CCE"

echo -e "${GREEN}Setting up Ubuntu test container for CCE...${NC}"

# 1. Stop and remove existing container if it exists
echo -e "${YELLOW}Cleaning up existing container...${NC}"
docker stop $CONTAINER_NAME 2>/dev/null || true
docker rm $CONTAINER_NAME 2>/dev/null || true

# 2. Run Ubuntu container with privileged mode (to run its own Docker daemon)
echo -e "${YELLOW}Starting Ubuntu container in privileged mode...${NC}"
docker run -d \
  --name $CONTAINER_NAME \
  --privileged \
  -p 8080:80 \
  -p 8443:443 \
  -p 8000:8000 \
  -p 3000:3000 \
  ubuntu:22.04 \
  sleep infinity

# 3. Install basic dependencies and Docker in container
echo -e "${YELLOW}Installing dependencies and Docker in container...${NC}"
docker exec $CONTAINER_NAME bash -c "
  apt-get update && \
  apt-get install -y \
    curl \
    git \
    ca-certificates \
    gnupg \
    lsb-release \
    sudo \
    iptables

  # Add Docker's official GPG key
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  # Add the repository to Apt sources
  echo \
    \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
    \$(. /etc/os-release && echo \"\$VERSION_CODENAME\") stable\" | \
    tee /etc/apt/sources.list.d/docker.list > /dev/null

  # Install Docker
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
"

# 4. Start Docker daemon inside the container with VFS driver (most compatible for DinD)
echo -e "${YELLOW}Starting Docker daemon inside the container...${NC}"
docker exec -d $CONTAINER_NAME bash -c "dockerd --storage-driver vfs > /var/log/dockerd.log 2>&1"

# Wait for Docker to start
echo -e "${YELLOW}Waiting for Docker to start inside container...${NC}"
for i in {1..30}; do
  if docker exec $CONTAINER_NAME docker info >/dev/null 2>&1; then
    echo -e "${GREEN}Docker is ready!${NC}"
    break
  fi
  if [ $i -eq 30 ]; then
    echo -e "${RED}Docker failed to start inside container. Check logs with: docker exec $CONTAINER_NAME cat /var/log/dockerd.log${NC}"
    exit 1
  fi
  sleep 1
done


# 5. Copy CCE directory to container
echo -e "${YELLOW}Copying CCE directory to container...${NC}"
docker cp $CCE_SOURCE $CONTAINER_NAME:/root/CCE

# 6. Set proper permissions
docker exec $CONTAINER_NAME bash -c "
  chmod +x /root/CCE/deploy/*.sh
"

echo -e "${GREEN}✅ Ubuntu test container setup complete!${NC}"
echo ""
echo -e "${GREEN}Container Details:${NC}"
echo "  Name: $CONTAINER_NAME"
echo "  CCE Location: /root/CCE"
echo ""
echo -e "${GREEN}Port Mappings:${NC}"
echo "  80 (nginx) -> 8080 (host)"
echo "  443 (nginx SSL) -> 8443 (host)"
echo "  8000 (backend) -> 8000 (host)"
echo "  3000 (frontend) -> 3000 (host)"
echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo "  1. Enter the container:"
echo "     docker exec -it $CONTAINER_NAME bash"
echo ""
echo "  2. Navigate to CCE directory:"
echo "     cd /root/CCE"
echo ""
echo "  3. Run setup script (if you have one):"
echo "     bash deploy/setup_vm.sh"
echo ""
echo "  4. Deploy the application:"
echo "     cd deploy && bash deploy.sh"
echo ""
echo -e "${YELLOW}To stop the container:${NC}"
echo "  docker stop $CONTAINER_NAME"
echo ""
echo -e "${YELLOW}To remove the container:${NC}"
echo "  docker rm $CONTAINER_NAME"
