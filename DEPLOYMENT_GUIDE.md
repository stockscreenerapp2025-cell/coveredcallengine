# CCE Deployment & Workflows Documentation

This document provides a detailed explanation of each file within the `.github/workflows` and `deploy` directories, as well as the logic behind their implementation.

---

## 📂 `.github/workflows`

### `ci.yml`
*   **Purpose**: Orchestrates Continuous Integration (CI) for both the backend and frontend modules on every push or pull request to the `main` or `master` branches.
*   **Permissions**: Securely configured with `contents: read` to restrict the GitHub token's scope to read-only access for the repository content.
*   **Backend Steps**: Automatically sets up a Python 3.12 environment, installs dependencies from `requirements.txt`, and runs the test suite to ensure code quality.
*   **Frontend Steps**: Configures Node.js 20, installs packages using `npm ci --legacy-peer-deps` for reproducible builds, and validates the build process.
*   **Security Auditing**: Executes `bandit` on the backend to find common security issues and `yarn audit` (or npm equivalent) on the frontend for dependency vulnerabilities.
*   **Linting**: Runs `flake8` for Python styling and basic lint checks for the frontend to maintain a consistent and clean codebase.
*   **Concurrency**: Uses `concurrency` groups to cancel in-progress runs when a new push is made, saving GitHub Actions minutes and providing faster feedback.
*   **Failure Notifications**: Designed to halt the pipeline if any build or test step fails, preventing unstable code from moving toward the deployment phase.

### `deploy.yml`
*   **Purpose**: Manages Continuous Deployment (CD) by automatically triggering a deployment to the production server via SSH after a successful push to `main`.
*   **Trigger Mechanism**: Specifically watches for changes on the `main` or `master` branches, ensuring that only stabilized code is sent to production.
*   **Environment Setup**: Defines a `production` environment, allowing for the use of environment-specific secrets and protections within GitHub.
*   **SSH Action**: Utilizes `appleboy/ssh-action` to securely connect to the remote host using secrets provided in the repository settings (HOST, KEY, USER).
*   **Secure Secrets**: Relies on `secrets.HOST`, `secrets.USERNAME`, and `secrets.SSH_KEY` to prevent sensitive credentials from being hardcoded in the codebase.
*   **Deployment Script Execution**: Remote commands navigate to the project directory, pull the latest changes, and execute the `deploy.sh` script to rebuild containers.
*   **Pipeline Flow**: Features a `script_stop: true` configuration, which ensures that the deployment job fails immediately if any command on the server returns an error.
*   **Deployment Logs**: Captures and displays the output of the server-side deployment process directly in the GitHub Actions log for easy troubleshooting.

---

## 📂 `deploy`

### `Dockerfile.backend`
*   **Base Image**: Uses `python:3.12-slim` to provide an updated and performance-oriented environment while keeping the image size minimal.
*   **System Dependencies**: Installs essential libraries like `gcc`, `libpq-dev`, and `curl` which are necessary for compiling certain Python packages and health checks.
*   **Security Hardening**: Creates a dedicated non-root user (`appuser`) and group (`appgroup`) to run the application, adhering to the principle of least privilege.
*   **Optimization**: Sets `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1` to optimize Python's execution inside the containerized environment.
*   **Dependency Management**: Copies `requirements.txt` and uses `pip install --no-cache-dir` to reduce image bloat and prevent redundant data storage.
*   **Permissions**: Changes ownership of the application directory to the non-root `appuser` before the application starts, preventing unauthorized filesystem access.
*   **Port Exposure**: Explicitly exposes port `8000`, the default port for the FastAPI server, to facilitate internal container communication.
*   **Health Check**: Includes a `HEALTHCHECK` command that uses `curl` to ping the `/api/health` endpoint, allowing Docker to monitor the container's vitality.

### `Dockerfile.frontend`
*   **Multi-Stage Build**: Implementation utilizes a `build` stage for compilation and an `nginx` stage for production serving, significantly reducing the final image size.
*   **Environment Variables**: Uses `ARG` and `ENV` to inject `REACT_APP_BACKEND_URL` during the build process, ensuring the frontend knows where the API is located.
*   **Dependency Installation**: Handles different lockfiles (`yarn.lock` or `package-lock.json`) and uses `--legacy-peer-deps` to resolve complex React dependency trees.
*   **Production Serving**: Uses `nginx:alpine` as the base for the final stage, providing a high-performance, lightweight web server for the static React assets.
*   **Nginx Configuration**: Injects a custom `default.conf` that properly handles Single Page Application (SPA) routing using `try_files $uri $uri/ /index.html`.
*   **Non-Root Security**: Re-configures Nginx to run as `appuser`, including updating permissions for cache, logs, and the PID file to allow execution without root access.
*   **Cleanup**: Automatically deletes build-time dependencies and the Node.js runtime from the final container, leaving only the static files and the Nginx server.
*   **Build Optimization**: Runs `npm run build` within the container to ensure that the production assets are minified and optimized for delivery over the web.

### `docker-compose.yml`
*   **Local Development**: Primary configuration for local testing, optimized for accessibility with ports like `3000`, `8000`, and `27017` mapped directly to the host.
*   **Services**: Orchestrates three main containers: `backend` (FastAPI), `frontend` (React/Nginx), and `mongodb` (Database), providing a complete stack.
*   **Networking**: Defines a custom bridge network `cce_network` to allow services to communicate using container names (e.g., `http://mongodb:27017`).
*   **Host Persistence**: Maps MongoDB data directly to the host directory `./mongo_data`, ensuring test data is preserved and easily accessible on the filesystem.
*   **Environment Configuration**: Supplies default local values for `MONGO_URL` and `REACT_APP_BACKEND_URL` (pointing to `localhost:8000`).
*   **Build Contexts**: Points to the respective source directories (`../backend` and `../frontend`) for building images, enabling easy updates during development.
*   **Restart Policy**: Uses `restart: always` (or similar) to ensure that services recover automatically if they crash or if the Docker daemon restarts.
*   **Storage Strategy**: Shifts from named volumes to direct file-system mapping, allowing users to backup or inspect the database files locally without complex Docker commands.

### `docker-compose.prod.yml`
*   **Production Hardening**: Extends the base configuration with security-focused settings, such as resource limits (memory/CPU) and dropped system capabilities.
*   **Reverse Proxy Integration**: Adds a `certbot` container to manage Let's Encrypt SSL certificates automatically, ensuring the site is served over HTTPS.
*   **Localized Volume Strategy**: Uses host-mounted storage at `./mongo_data` for the database, bypassing external named volumes for easier localized retention.
*   **Network Isolation**: Limits port exposure; only the Nginx container exposes ports `80` and `443`, while the app services remain hidden behind the firewall.
*   **Resource Management**: Implements `deploy.resources` limits to prevent a single container from consuming all system resources, protecting against certain DoS attacks.
*   **Environment Mapping**: Relies on host-defined environment variables or secrets, such as production database URLs and API endpoints.
*   **Graceful Shutdown**: Configured with appropriate `stop_grace_period` set to allow the backend and database to finish active tasks before terminating.
*   **Host Storage Management**: Aligns with `init_dirs.sh` to ensure the local storage path is initialized with correct permissions for the MongoDB container user.

### `deploy.sh`
*   **Automation Hub**: The primary entry point for deploying the application on the production server, coordinating multiple sub-scripts and Docker commands.
*   **Code Update**: Performs a `git pull origin main` to fetch the latest changes from the repository before initiating the rebuild process.
*   **Directory Initialization**: Executes `init_dirs.sh` to ensure that all necessary mount points (logs, data) exist on the host filesystem.
*   **Volume Management**: Checks for and creates the production MongoDB volume if it's missing, preventing data loss during first-time setup.
*   **Smart Compose**: Logic automatically detects whether to use `docker-compose.prod.yml` or the standard version based on the environment's file availability.
*   **Rebuild Logic**: Runs `docker compose up -d --build`, which rebuilds images only if changes are detected, minimizing downtime.
*   **System Cleanup**: Executes `docker image prune -f` at the end to delete dangling images, keeping the server's storage usage efficient.
*   **Health Verification**: Outputs the expected local URLs for the frontend and backend documentation as a quick check for the administrator.

### `init_letsencrypt.sh`
*   **SSL Orchestration**: A specialized script designed to bootstrap the Let's Encrypt SSL process using the `certbot` Docker container.
*   **Dummy Certificates**: Initially creates "fake" certificates to allow Nginx to start, resolving the "chicken and egg" problem where Nginx needs certificates to run the ACME challenge.
*   **ACME Protocol**: Coordinates with the Let's Encrypt servers to validate domain ownership via the `.well-known/acme-challenge/` directory.
*   **Automatic Renewal**: Configured to set up a cron job or a background process that checks and renews certificates before they expire every 90 days.
*   **Domain Configuration**: Maps the specific domains (e.g., `cce.coveredcallengine.com`) and the admin email for recovery and expiry notifications.
*   **Cleanup**: Once real certificates are obtained, the script replaces the dummy files and reloads the Nginx container to apply the secure configuration.
*   **Dry Run Support**: Includes a `staging` flag that can be toggled to test the setup against Let's Encrypt's test servers, avoiding rate limits.
*   **RSA Key Generation**: Generates 4096-bit RSA keys, providing a high level of cryptographic security for the server's identity.

### `init_dirs.sh`
*   **Filesystem Preparation**: Ensures that all external volumes required by Docker containers are present on the host system before deployment.
*   **Directory Creation**: Creates the `mongo_data` folder for database persistence and a `logs` directory for application and Nginx output.
*   **Permission Fixes**: Sets specific permissions (e.g., `chmod 777` or appropriate ownership) to prevent "Permission Denied" errors when containers try to write data.
*   **Variable Pathing**: Uses `SCRIPT_DIR` to resolve absolute paths, making the script reliable regardless of which directory it's executed from.
*   **Safety Checks**: Uses `mkdir -p` to avoid errors if directories already exist, making the script idempotent and safe to run multiple times.
*   **Validation**: Prints a summary of the created directories at the end, allowing the user to verify the setup immediately.
*   **Standardization**: Provides a single source of truth for the project's directory structure, preventing configuration drift across different servers.

### `setup_vm.sh`
*   **Base Provisioning**: A comprehensive script for preparing a fresh Ubuntu/Debian VM with all the software required to run CCE.
*   **Dependency Management**: Installs `curl`, `git`, and `build-essential` which are required for subsequent installation steps and code management.
*   **Language Runtime**: Automatically installs Python 3.12 and its development headers using the `deadsnakes` PPA, ensuring the backend environment is matched.
*   **Frontend Runtime**: Sets up Node.js using the official NodeSource repository, providing the stable environment needed for building the React application.
*   **Docker Engine**: Installs the Docker Engine and the Docker Compose plugin directly from Docker's official repositories for the most up-to-date features.
*   **User Permissions**: Adds the current user to the `docker` group, allowing the user to manage containers without needing `sudo` for every command.
*   **Environment Verification**: Performs a final "Prerequisites Check" at the end, printing green checkmarks for each successfully installed component.
*   **Portability**: While optimized for Ubuntu, it includes logic to detect other distributions and provide helpful warnings rather than failing cryptically.

### `local/deploy_local_mac.sh`
*   **Mac Local Experience**: Tailored specifically for macOS users to get the CCE stack running locally with a single command.
*   **Platform Detection**: Checks `uname` to ensure the script isn't accidentally run on an unsupported OS like Linux or Windows.
*   **Docker Desktop Check**: Verifies that Docker Desktop is not only installed but also currently running, which is a common point of failure for Mac users.
*   **Automation**: Combines directory initialization (`init_dirs.sh`) and Docker Compose commands into a single seamless workflow.
*   **Relative Pathing**: Reliably finds the project files using `../` logic to access the parent `deploy` folder from the `local` directory.
*   **Developer Friendly**: Prints clear instructions at the end on how to access the app and how to shut it down properly.
*   **Isolation**: Uses the dev-specific `docker-compose.yml` to avoid conflicts with production settings like SSL or complex resource limits.
*   **Troubleshooting**: Provides direct links to Docker documentation if the environment is not set up correctly, reducing the developer's research time.

### `local/deploy_local_windows.sh`
*   **Windows Environment Check**: Designed to detect Git Bash, WSL, or MSYS environments commonly used by developers on Windows.
*   **Prerequisite Validation**: Ensures that Docker Desktop for Windows is installed and the daemon is active before proceeding with the build.
*   **Universal Scripting**: Utilizes Bash syntax to provide a familiar experience for cross-platform developers while targeting Windows-specific issues.
*   **Automation Loop**: Orchestrates the entire local setup, including automated directory creation via the shared `init_dirs.sh` utility.
*   **Scoped Configuration**: Targets the local `docker-compose.yml` file in the parent directory to prevent accidental production deployments.
*   **User Guidance**: Provides direct download links for Docker Desktop for Windows and troubleshooting steps for daemon startup issues.
*   - **Consistent UI**: Maintains the same color-coded output and success messaging as the Mac version for a unified developer experience.
*   - **Lifecycle Management**: Includes simple commands for stopping the local stack, ensuring the developer can easily manage their local resources.

### `nginx/conf.d/app.conf`
*   **Hardened Traffic Management**: Acts as the production reverse proxy, now upgraded with anti-DDoS measures and strict connection management.
*   **SSL & HTTP/2 Modernization**: Enforces HTTPS redirection and uses the modern `http2 on;` directive for optimized, secure multiplexed connections.
*   **DDoS & Buffer Protection**: Implements strict buffer limits (`client_body_buffer_size`, etc.) to mitigate Slowloris and large-payload exhaustion attacks.
*   **Timeout Hardening**: Sets aggressive timeouts for headers and body reading (`client_body_timeout`, etc.) to terminate hung or malicious connections quickly.
*   **Method Restriction**: Uses an allowed-list approach to strictly permit only `GET`, `POST`, `HEAD`, `OPTIONS`, `PUT`, `DELETE`, and `PATCH` methods.
*   **Advanced Security Headers**: Includes `Permissions-Policy` to disable unused browser features (camera, geolocation) and hides `X-Powered-By` information headers.
*   **Dual-Layer Throttling**: Combines IP-based rate limiting (`limit_req`) with connection limiting (`limit_conn`) to prevent API abuse and resource saturation.
*   **Global Zone Scope**: Configures rate-limiting zones at the global level to ensure consistent enforcement across all proxied microservices.

### `.env.example`
*   **Template Definition**: Provides a comprehensive list of all required environment variables, acting as a blueprint for the production `.env` file.
*   **Security Best Practices**: Includes placeholder values for sensitive data like `JWT_SECRET` and `MONGO_URL`, signaling to the user that these must be changed.
*   **Configuration Scope**: Covers database connections, API keys for external services (Polygon, OpenAI, Stripe), and application metadata.
*   **Documentation**: Contains comments for each variable explaining its purpose and the format expected by the application logic.
*   **Portability**: Allows the stack to be configured for different environments (Stage, Prod, QA) simply by creating multiple versions of the actual `.env` file.
*   **Developer Onboarding**: Significantly reduces the time required for a new developer to set up the project by providing a clear list of configuration needs.
*   **Version Control Safety**: By being named `.example`, it identifies itself as a safe file to commit, while the real `.env` is typically ignored by Git.

---
