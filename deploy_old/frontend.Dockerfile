FROM node:20-alpine

WORKDIR /app

# Install dependencies
# No lockfile present, so we copy just package.json and run install
COPY package.json ./

# Yarn install might fail on network or compatibility, but we just updated node version
RUN yarn install

COPY . .

EXPOSE 3000

# Start the application
CMD ["yarn", "start"]
