#!/usr/bin/env python3
"""
"Usable" means: a docker binary that belongs to THIS system (on Linux/WSL,
Windows binaries under /mnt/ are ignored) and a daemon that answers.

Usage:
    python Auton8nDeployment.py
    python Auton8nDeployment.py --workflows ./mis_workflows
    python Auton8nDeployment.py --puerto 5679 --no-navegador
    python Auton8nDeployment.py --actualizar     # pull latest image and recreate the container
    python Auton8nDeployment.py --parar          # stop the container (data is kept)
"""

import argparse
import getpass
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser

SISTEMA = platform.system()  # Windows / Darwin / Linux
IMAGEN = "docker.n8n.io/n8nio/n8n:latest"
CONTENEDOR = "n8n"
VOLUMEN = "n8n_data"

# Command prefix used for every docker call. It can become ["sudo", "/usr/bin/docker"]
# right after a fresh install, when the user is not yet in the docker group.
DOCKER = ["docker"]


def run(cmd, **kw):
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, **kw)


def salida(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


# ---------------------------------------------------------------- Docker
def buscar_docker():
    """
    Locate a docker binary native to this system.
    On Linux/WSL, PATH entries under /mnt/ (Windows) are skipped, otherwise
    Docker Desktop's docker.exe wrapper can be picked up without a real engine.
    """
    if SISTEMA == "Linux":
        limpio = os.pathsep.join(
            p for p in os.environ.get("PATH", "").split(os.pathsep)
            if not p.startswith("/mnt/")
        )
        return shutil.which("docker", path=limpio)
    return shutil.which("docker")


def demonio_activo():
    global DOCKER
    r = subprocess.run(DOCKER + ["info"], capture_output=True, text=True)
    if r.returncode == 0:
        return True
    # Freshly installed: this session doesn't have the docker group yet -> fall back to sudo
    if (SISTEMA == "Linux" and "permission denied" in (r.stderr or "").lower()
            and DOCKER[0] != "sudo"):
        print("[i] Sin permisos sobre el socket de Docker en esta sesión, uso sudo.")
        DOCKER = ["sudo"] + DOCKER
        return subprocess.run(DOCKER + ["info"], capture_output=True).returncode == 0
    return False


def servicio_docker_existe():
    """True if systemd knows a docker.service unit (i.e. a real engine is installed)."""
    r = subprocess.run(["systemctl", "list-unit-files", "docker.service"],
                       capture_output=True, text=True)
    return "docker.service" in (r.stdout or "")


def instalar_docker():
    print("[!] No hay un Docker utilizable, intentando instalarlo...")
    try:
        if SISTEMA == "Windows":
            if not shutil.which("winget"):
                sys.exit("[x] No hay winget. Instala Docker Desktop a mano: https://www.docker.com/products/docker-desktop")
            run(["winget", "install", "-e", "--id", "Docker.DockerDesktop",
                 "--accept-source-agreements", "--accept-package-agreements"], check=True)
        elif SISTEMA == "Darwin":
            if not shutil.which("brew"):
                sys.exit("[x] No hay brew. Instala Docker Desktop a mano: https://www.docker.com/products/docker-desktop")
            run(["brew", "install", "--cask", "docker"], check=True)
        else:
            if not shutil.which("curl"):
                sys.exit("[x] Falta curl para instalar Docker. Instálalo y reintenta.")
            # Official convenience script (on WSL it waits 20s and shows a warning, that's normal)
            run(["sh", "-c", "curl -fsSL https://get.docker.com | sudo sh"], check=True)
            run(["sudo", "systemctl", "enable", "--now", "docker"])
            # Let the current user run docker without sudo (needs a new login to take effect)
            run(["sudo", "usermod", "-aG", "docker", getpass.getuser()])
    except subprocess.CalledProcessError as e:
        sys.exit(f"[x] Falló la instalación de Docker: {e}")


def preparar_docker():
    """Make sure a native docker binary exists and its daemon answers."""
    global DOCKER

    ruta = buscar_docker()
    if not ruta:
        instalar_docker()
        ruta = buscar_docker()
        if not ruta:
            # PATH is not refreshed in the current session right after installing (Windows/Mac)
            sys.exit("[!] Docker instalado pero no aparece en el PATH. "
                     "Reinicia la sesión/terminal (en Windows puede pedir reinicio) y vuelve a ejecutar.")
    DOCKER = [ruta]

    if demonio_activo():
        return

    # Binary present but daemon down. On Linux with no docker.service there is no
    # engine at all (e.g. only a client), so install it instead of trying to start it.
    if SISTEMA == "Linux" and not servicio_docker_existe():
        instalar_docker()
        ruta = buscar_docker()
        if not ruta:
            sys.exit("[x] No se pudo instalar Docker Engine.")
        DOCKER = [ruta]
        if demonio_activo():
            return

    arrancar_demonio()


def arrancar_demonio():
    print("[!] El demonio de Docker no responde, intentando arrancarlo...")
    if SISTEMA == "Windows":
        ruta = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                            "Docker", "Docker", "Docker Desktop.exe")
        if os.path.exists(ruta):
            subprocess.Popen([ruta])
    elif SISTEMA == "Darwin":
        run(["open", "-a", "Docker"])
    else:
        run(["sudo", "systemctl", "start", "docker"])

    # Wait for the daemon to come up (up to ~3 min, Docker Desktop is slow)
    for _ in range(60):
        if demonio_activo():
            print("[✓] Docker listo.")
            return
        time.sleep(3)
    sys.exit("[x] Docker no arrancó a tiempo. Ábrelo a mano y reintenta.")


# ---------------------------------------------------------------- Container
def estado_contenedor():
    """Return 'running', 'exited', etc., or '' if the container doesn't exist."""
    return salida(DOCKER + ["inspect", "-f", "{{.State.Status}}", CONTENEDOR])


def importar_workflows(carpeta):
    carpeta = os.path.abspath(carpeta)
    if not os.path.isdir(carpeta):
        print(f"[!] La carpeta {carpeta} no existe, salto la importación.")
        return
    print(f"[+] Importando workflows desde {carpeta}...")
    # One-off container sharing the data volume; folder mounted read-only
    r = run(DOCKER + ["run", "--rm",
                      "-v", f"{VOLUMEN}:/home/node/.n8n",
                      "-v", f"{carpeta}:/workflows:ro",
                      IMAGEN, "import:workflow", "--separate", "--input=/workflows"])
    if r.returncode != 0:
        print("[!] La importación dio error (revisa los JSON), sigo igualmente.")


def crear_contenedor(puerto, tz):
    print(f"[+] Creando contenedor '{CONTENEDOR}' en el puerto {puerto}...")
    r = run(DOCKER + ["run", "-d",
                      "--name", CONTENEDOR,
                      "--restart", "unless-stopped",
                      "-p", f"{puerto}:5678",
                      "-v", f"{VOLUMEN}:/home/node/.n8n",
                      "-e", f"GENERIC_TIMEZONE={tz}",
                      "-e", f"TZ={tz}",
                      "-e", "N8N_SECURE_COOKIE=false",  # allow plain http access on localhost
                      IMAGEN])
    if r.returncode != 0:
        sys.exit("[x] No se pudo crear el contenedor (¿puerto ocupado?).")


def esperar_n8n(puerto, timeout=120):
    """Poll the health endpoint until n8n answers 200 or the timeout expires."""
    url = f"http://localhost:{puerto}/healthz"
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def puerto_publicado():
    """Host port mapped to the container's 5678 (for an already existing container)."""
    out = salida(DOCKER + ["port", CONTENEDOR, "5678/tcp"])
    return int(out.splitlines()[0].rsplit(":", 1)[1]) if out else None


# Main !!!!!!
def main():
    ap = argparse.ArgumentParser(description="Instala Docker y despliega n8n en contenedor")
    ap.add_argument("--puerto", type=int, default=5678, help="puerto del host (def. 5678)")
    ap.add_argument("--workflows", help="carpeta con workflows .json a importar")
    ap.add_argument("--zona-horaria", default="Europe/Madrid", help="def. Europe/Madrid")
    ap.add_argument("--no-navegador", action="store_true", help="no abrir el navegador")
    ap.add_argument("--actualizar", action="store_true", help="bajar última imagen y recrear")
    ap.add_argument("--parar", action="store_true", help="parar el contenedor y salir")
    args = ap.parse_args()

    # Docker: install if there is no usable one, start the daemon if it's down
    preparar_docker()
    print(f"[✓] Docker OK ({' '.join(DOCKER)})")

    estado = estado_contenedor()

    # Stop and exit
    if args.parar:
        if estado == "running":
            run(DOCKER + ["stop", CONTENEDOR])
        else:
            print("[i] El contenedor no está corriendo.")
        return

    # Update: pull the latest image and recreate the container
    if args.actualizar:
        run(DOCKER + ["pull", IMAGEN])
        if estado:
            run(DOCKER + ["rm", "-f", CONTENEDOR])
            estado = ""

    # Import workflows while n8n is stopped / not created yet,
    #    so we don't write to the DB while the app is using it
    if args.workflows:
        if estado == "running":
            run(DOCKER + ["stop", CONTENEDOR])
            estado = "exited"
        run(DOCKER + ["volume", "create", VOLUMEN], capture_output=True)
        importar_workflows(args.workflows)

    # Bring n8n up: create, start or reuse the running one
    puerto = args.puerto
    if not estado:
        crear_contenedor(puerto, args.zona_horaria)
    elif estado != "running":
        print(f"[+] Arrancando contenedor existente '{CONTENEDOR}'...")
        run(DOCKER + ["start", CONTENEDOR])
        puerto = puerto_publicado() or puerto  # keep the port it was created with
    else:
        print("[i] n8n ya estaba corriendo.")
        puerto = puerto_publicado() or puerto

    # Wait until it's healthy and open the browser
    url = f"http://localhost:{puerto}"
    if esperar_n8n(puerto):
        print(f"[✓] n8n listo en {url}")
        if not args.no_navegador:
            webbrowser.open(url)
    else:
        print(f"[!] n8n no respondió a tiempo. Mira los logs: {' '.join(DOCKER)} logs {CONTENEDOR}")

    print(f"\nComandos útiles:\n  {' '.join(DOCKER)} logs -f {CONTENEDOR}\n"
          f"  python {os.path.basename(__file__)} --parar\n"
          f"  python {os.path.basename(__file__)} --actualizar")


if __name__ == "__main__":
    main()