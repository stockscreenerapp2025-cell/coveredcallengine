# Production Frontend Dockerfile
# Multi-stage build: Build with Node → Serve with Nginx

# Stage 1: Build the React application
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package.json yarn.lock* ./

# Install dependencies
RUN yarn install --frozen-lockfile 2>/dev/null || yarn install

# Copy source code
COPY . .

# Build argument for API URL
ARG REACT_APP_BACKEND_URL=https://cce.coveredcallengine.com/api
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL

# Build the production bundle
RUN yarn build

# Stage 2: Serve with Nginx
FROM nginx:alpine

# Copy built assets from builder stage
COPY --from=builder /app/build /usr/share/nginx/html

# Copy custom nginx config for SPA routing
COPY frontend-nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Start Nginx
CMD ["nginx", "-g", "daemon off;"]
