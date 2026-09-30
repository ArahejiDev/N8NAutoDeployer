# Auton8nDeployment

One-command deployment of [n8n](https://n8n.io) in Docker. If there is no usable Docker on the machine, the script installs it first.

Pure Python 3, standard library only. Works on Windows, macOS, Linux and WSL2.

## What it does

1. Looks for a **native** Docker binary. On Linux/WSL, Windows binaries under `/mnt/` (e.g. Docker Desktop's `docker.exe`) are ignored.
2. Installs Docker if it is missing (or if only a client without an engine is found).
3. Starts the Docker daemon if it is down.
4. Optionally imports your workflow JSON files.
5. Creates (or reuses) an `n8n` container with a persistent volume and `--restart unless-stopped`.
6. Waits for `/healthz` and opens the browser at `http://localhost:5678`.

## Requirements

- Python 3.8+
- Internet access
- `sudo` rights on Linux/WSL, and `winget` (Windows) or `brew` (macOS) if Docker has to be installed

## Quick start

```bash
python Auton8nDeployment.py
```

Then open <http://localhost:5678> and create your owner account.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--puerto N` | Host port for n8n | `5678` |
| `--workflows DIR` | Folder with workflow `.json` files to import | – |
| `--zona-horaria TZ` | Timezone for the container | `Europe/Madrid` |
| `--no-navegador` | Do not open the browser | off |
| `--actualizar` | Pull the latest image and recreate the container | off |
| `--parar` | Stop the container and exit (data is kept) | off |

### Examples

```bash
# Custom port, no browser
python Auton8nDeployment.py --puerto 5679 --no-navegador

# Import workflows before starting
python Auton8nDeployment.py --workflows ./workflows

# Update to the latest n8n version
python Auton8nDeployment.py --actualizar

# Stop n8n
python Auton8nDeployment.py --parar
```

## Data persistence

Workflows, credentials and executions live in the Docker volume `n8n_data`, so they survive restarts and `--actualizar`.

To wipe everything:

```bash
docker rm -f n8n
docker volume rm n8n_data
```

## Notes per platform

**Windows** – Docker Desktop is installed with `winget`. It may ask for a reboot or WSL2 setup. If the PATH is not refreshed after installing, open a new terminal and run the script again.

**macOS** – Docker Desktop is installed with `brew install --cask docker`.

**Linux** – Docker Engine is installed with the official `get.docker.com` script and your user is added to the `docker` group. Until you log in again, the script falls back to `sudo docker` automatically.

**WSL2** – Requires systemd (`[boot]` → `systemd=true` in `/etc/wsl.conf`, then `wsl --shutdown`). The Docker installer shows a 20-second warning recommending Docker Desktop; it continues on its own. Use `--no-navegador` and open `http://localhost:5678` from Windows.

### Testing without touching your system (WSL2)

```powershell
wsl --install -d Ubuntu-24.04 --name n8n-test
# ... run the script inside that distro ...
wsl --unregister n8n-test   # delete everything when done
```

## Security

The container is started with `N8N_SECURE_COOKIE=false` so you can log in over plain `http://localhost`. This is meant for **local use only**. If you expose n8n to a network, put it behind a reverse proxy with HTTPS and remove that variable.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Docker no arrancó a tiempo` | Start Docker manually and re-run the script |
| `permission denied` on the Docker socket | Log out and back in (or `newgrp docker`); the script already retries with `sudo` |
| `Unit docker.service not found` on WSL | Enable systemd (see above); the script installs the engine if none exists |
| Port already in use | Use `--puerto` with a free port |
| n8n does not respond in time | `docker logs -f n8n` |

## Useful commands

```bash
docker logs -f n8n     # follow logs
docker ps              # check the container
docker exec -it n8n sh # shell inside the container
```
