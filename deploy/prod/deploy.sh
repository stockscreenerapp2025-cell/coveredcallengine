#!/bin/bash
# ================================================
# CCE Production Deployment Script
# ================================================
# Usage: ./deploy.sh [first-run|update|ssl-only]
# ================================================

set -e

DOMAIN="cce.coveredcallengine.com"
EMAIL="sray68@gmail.com"  # For SSL cert notifications

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  CCE Production Deployment${NC}"
echo -e "${GREEN}========================================${NC}"

# Check if .env.production exists
if [ ! -f ".env.production" ]; then
    echo -e "${RED}ERROR: .env.production not found!${NC}"
    echo "Copy .env.example to .env.production and fill in your secrets:"
    echo "  cp .env.example .env.production"
    exit 1
fi

# Function to get SSL certificate
get_ssl_cert() {
    echo -e "${YELLOW}Getting SSL certificate for ${DOMAIN}...${NC}"
    
    # Create certbot directories
    mkdir -p certbot/conf certbot/www
    
    # Stop nginx if running
    docker compose down nginx 2>/dev/null || true
    
    # Get certificate using standalone mode
    docker run --rm -it \
        -v "$(pwd)/certbot/conf:/etc/letsencrypt" \
        -v "$(pwd)/certbot/www:/var/www/certbot" \
        -p 80:80 \
        certbot/certbot certonly \
        --standalone \
        --email $EMAIL \
        --agree-tos \
        --no-eff-email \
        -d $DOMAIN
    
    echo -e "${GREEN}SSL certificate obtained!${NC}"
}

# Function to build and start services
start_services() {
    echo -e "${YELLOW}Building and starting services...${NC}"
    
    docker compose --env-file .env.production build --no-cache
    docker compose --env-file .env.production up -d
    
    echo -e "${GREEN}Services started!${NC}"
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Deployment Complete!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Frontend: https://${DOMAIN}"
    echo "API Docs: https://${DOMAIN}/api/docs"
    echo ""
    echo "View logs: docker compose logs -f"
}

# Function for first-time deployment
first_run() {
    echo -e "${YELLOW}First-time deployment...${NC}"
    
    # Get SSL certificate first
    get_ssl_cert
    
    # Build and start all services
    start_services
}

# Function to update existing deployment
update() {
    echo -e "${YELLOW}Updating deployment...${NC}"
    
    # Pull latest code (if using git)
    # git pull origin main
    
    # Rebuild and restart
    docker compose --env-file .env.production build
    docker compose --env-file .env.production up -d
    
    echo -e "${GREEN}Update complete!${NC}"
}

# Main script
case "${1:-update}" in
    first-run)
        first_run
        ;;
    ssl-only)
        get_ssl_cert
        ;;
    update)
        update
        ;;
    *)
        echo "Usage: $0 [first-run|update|ssl-only]"
        echo ""
        echo "  first-run  - First deployment (gets SSL cert + starts services)"
        echo "  update     - Update existing deployment"
        echo "  ssl-only   - Only get/renew SSL certificate"
        exit 1
        ;;
esac
