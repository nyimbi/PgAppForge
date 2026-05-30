"""
Deploy command group for Flask-AppBuilder generated applications.

Supports:
  Docker:  build, push, run, start, stop, restart, status, logs, exec
  Server:  push (rsync/SCP), start, stop, restart, status, logs

Config file: .fab-deploy.yml in the project root, e.g.:

    app_name: myapp
    image: myregistry/myapp:latest

    docker:
      dockerfile: Dockerfile
      compose_file: docker-compose.yml
      container_name: myapp_web

    server:
      host: myserver.example.com
      user: deploy
      port: 22
      remote_dir: /opt/apps/myapp
      service_name: myapp          # systemd unit name, or null for bare process
      python: python3
      venv: /opt/apps/myapp/.venv
      restart_cmd: "sudo systemctl restart myapp"  # override if not systemd

Commands::

    flask fab deploy docker build
    flask fab deploy docker run
    flask fab deploy docker stop
    flask fab deploy docker restart
    flask fab deploy docker status
    flask fab deploy docker logs [--follow] [--tail N]
    flask fab deploy docker push [--tag TAG]

    flask fab deploy server push [--dry-run]
    flask fab deploy server start
    flask fab deploy server stop
    flask fab deploy server restart
    flask fab deploy server status
    flask fab deploy server logs [--follow] [--lines N]
    flask fab deploy server exec COMMAND
"""
from __future__ import annotations

import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Any

import click
import yaml


# ─── Config ──────────────────────────────────────────────────────────────────

def _find_config() -> Path | None:
	"""Find .fab-deploy.yml walking up from cwd."""
	current = Path.cwd()
	for directory in [current, *current.parents]:
		cfg = directory / ".fab-deploy.yml"
		if cfg.exists():
			return cfg
	return None


def _load_config(config_path: str | None = None) -> dict[str, Any]:
	"""Load deployment configuration."""
	if config_path:
		path = Path(config_path)
	else:
		path = _find_config()

	if not path or not path.exists():
		click.echo(
			"❌ No .fab-deploy.yml found. Run: flask fab deploy init",
			err=True,
		)
		sys.exit(1)

	with open(path) as f:
		cfg = yaml.safe_load(f) or {}

	return cfg


def _run(cmd: list[str], capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
	"""Run a shell command, streaming output by default."""
	click.echo(f"▶ {' '.join(cmd)}", err=True)
	if capture:
		return subprocess.run(cmd, check=check, capture_output=True, text=True)
	return subprocess.run(cmd, check=check)


# ─── Top-level deploy group ───────────────────────────────────────────────────

@click.group("deploy")
@click.option("--config", "-c", default=None, help="Path to .fab-deploy.yml")
@click.pass_context
def deploy(ctx, config):
	"""Deploy and manage a generated Flask-AppBuilder application."""
	ctx.ensure_object(dict)
	ctx.obj["config_path"] = config


# ─── Init ─────────────────────────────────────────────────────────────────────

@deploy.command("init")
@click.option("--app-name", prompt="App name", help="Application name")
@click.option("--image", prompt="Docker image name", default=lambda: "", help="e.g. registry/myapp:latest")
@click.option("--server-host", prompt="Server host (enter to skip)", default="", help="SSH host for server deploy")
@click.pass_context
def deploy_init(ctx, app_name, image, server_host):
	"""Generate a .fab-deploy.yml config file in the current directory."""
	cfg = {
		"app_name": app_name,
		"image": image or f"{app_name}:latest",
		"docker": {
			"dockerfile": "Dockerfile",
			"compose_file": "docker-compose.yml",
			"container_name": f"{app_name}_web",
			"port": 8080,
		},
	}
	if server_host:
		cfg["server"] = {
			"host": server_host,
			"user": "deploy",
			"port": 22,
			"remote_dir": f"/opt/apps/{app_name}",
			"service_name": app_name,
			"python": "python3",
			"venv": f"/opt/apps/{app_name}/.venv",
		}

	target = Path.cwd() / ".fab-deploy.yml"
	with open(target, "w") as f:
		yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
	click.echo(f"✅ Created {target}")
	click.echo("Edit it to match your environment, then run: flask fab deploy docker build")


# ─── Docker subgroup ──────────────────────────────────────────────────────────

@deploy.group("docker")
@click.pass_context
def deploy_docker(ctx):
	"""Docker build, push, and lifecycle management."""


@deploy_docker.command("build")
@click.option("--tag", "-t", default=None, help="Override image tag")
@click.option("--no-cache", is_flag=True, help="Build without Docker layer cache")
@click.pass_context
def docker_build(ctx, tag, no_cache):
	"""Build the Docker image."""
	cfg = _load_config(ctx.obj.get("config_path"))
	docker_cfg = cfg.get("docker", {})
	image = tag or cfg.get("image", cfg.get("app_name", "app"))
	dockerfile = docker_cfg.get("dockerfile", "Dockerfile")

	if not Path(dockerfile).exists():
		click.echo(f"❌ Dockerfile not found: {dockerfile}", err=True)
		sys.exit(1)

	cmd = ["docker", "build", "-t", image, "-f", dockerfile]
	if no_cache:
		cmd.append("--no-cache")
	cmd.append(".")

	_run(cmd)
	click.echo(f"✅ Built image: {image}")


@deploy_docker.command("push")
@click.option("--tag", "-t", default=None, help="Image tag to push")
@click.pass_context
def docker_push(ctx, tag):
	"""Push the Docker image to a registry."""
	cfg = _load_config(ctx.obj.get("config_path"))
	image = tag or cfg.get("image", cfg.get("app_name", "app"))
	_run(["docker", "push", image])
	click.echo(f"✅ Pushed: {image}")


@deploy_docker.command("run")
@click.option("--env-file", default=".env", help="Environment file to pass to container")
@click.option("--port", "-p", default=None, type=int, help="Host port to bind")
@click.option("--detach/--no-detach", default=True, help="Run in background (default)")
@click.pass_context
def docker_run(ctx, env_file, port, detach):
	"""Start the application container (docker run)."""
	cfg = _load_config(ctx.obj.get("config_path"))
	docker_cfg = cfg.get("docker", {})
	image = cfg.get("image", cfg.get("app_name", "app"))
	name = docker_cfg.get("container_name", cfg.get("app_name", "app"))
	host_port = port or docker_cfg.get("port", 8080)

	# Check if compose file exists — prefer compose
	compose_file = docker_cfg.get("compose_file", "docker-compose.yml")
	if Path(compose_file).exists():
		click.echo(f"ℹ Using docker compose ({compose_file})")
		_run(["docker", "compose", "-f", compose_file, "up", "--build", "-d" if detach else ""])
		return

	cmd = ["docker", "run", "--name", name]
	if detach:
		cmd.append("-d")
	if Path(env_file).exists():
		cmd += ["--env-file", env_file]
	cmd += ["-p", f"{host_port}:8080"]
	cmd.append(image)

	_run(cmd)
	click.echo(f"✅ Container started: {name}")
	if detach:
		click.echo(f"   View logs: flask fab deploy docker logs")
		click.echo(f"   Open:      http://localhost:{host_port}")


@deploy_docker.command("stop")
@click.pass_context
def docker_stop(ctx):
	"""Stop the running container."""
	cfg = _load_config(ctx.obj.get("config_path"))
	docker_cfg = cfg.get("docker", {})

	compose_file = docker_cfg.get("compose_file", "docker-compose.yml")
	if Path(compose_file).exists():
		_run(["docker", "compose", "-f", compose_file, "stop"])
		return

	name = docker_cfg.get("container_name", cfg.get("app_name", "app"))
	_run(["docker", "stop", name], check=False)
	click.echo(f"✅ Stopped: {name}")


@deploy_docker.command("restart")
@click.pass_context
def docker_restart(ctx):
	"""Restart the container."""
	cfg = _load_config(ctx.obj.get("config_path"))
	docker_cfg = cfg.get("docker", {})

	compose_file = docker_cfg.get("compose_file", "docker-compose.yml")
	if Path(compose_file).exists():
		_run(["docker", "compose", "-f", compose_file, "restart"])
		return

	name = docker_cfg.get("container_name", cfg.get("app_name", "app"))
	_run(["docker", "restart", name])
	click.echo(f"✅ Restarted: {name}")


@deploy_docker.command("status")
@click.pass_context
def docker_status(ctx):
	"""Show container status."""
	cfg = _load_config(ctx.obj.get("config_path"))
	docker_cfg = cfg.get("docker", {})

	compose_file = docker_cfg.get("compose_file", "docker-compose.yml")
	if Path(compose_file).exists():
		_run(["docker", "compose", "-f", compose_file, "ps"])
		return

	name = docker_cfg.get("container_name", cfg.get("app_name", "app"))
	result = _run(
		["docker", "inspect", "--format",
		 "{{.Name}} | {{.State.Status}} | {{.State.StartedAt}}", name],
		capture=True, check=False,
	)
	if result.returncode == 0:
		click.echo(result.stdout.strip())
	else:
		click.echo(f"Container '{name}' not found or not running.")


@deploy_docker.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--tail", "-n", default=100, help="Number of lines to show (default 100)")
@click.pass_context
def docker_logs(ctx, follow, tail):
	"""Stream container logs."""
	cfg = _load_config(ctx.obj.get("config_path"))
	docker_cfg = cfg.get("docker", {})

	compose_file = docker_cfg.get("compose_file", "docker-compose.yml")
	if Path(compose_file).exists():
		cmd = ["docker", "compose", "-f", compose_file, "logs", "--tail", str(tail)]
		if follow:
			cmd.append("-f")
		_run(cmd)
		return

	name = docker_cfg.get("container_name", cfg.get("app_name", "app"))
	cmd = ["docker", "logs", "--tail", str(tail), name]
	if follow:
		cmd.insert(-1, "-f")
	_run(cmd)


@deploy_docker.command("exec")
@click.argument("command", nargs=-1, required=True)
@click.pass_context
def docker_exec(ctx, command):
	"""Execute a command inside the running container."""
	cfg = _load_config(ctx.obj.get("config_path"))
	docker_cfg = cfg.get("docker", {})
	name = docker_cfg.get("container_name", cfg.get("app_name", "app"))
	_run(["docker", "exec", "-it", name] + list(command))


# ─── Server subgroup ──────────────────────────────────────────────────────────

@deploy.group("server")
@click.pass_context
def deploy_server(ctx):
	"""Deploy and manage on a remote server via SSH."""


def _ssh_run(srv_cfg: dict, command: str, pty: bool = False) -> int:
	"""Run a command on the remote server via SSH."""
	host = srv_cfg["host"]
	user = srv_cfg.get("user", "deploy")
	port = srv_cfg.get("port", 22)
	ssh_opts = ["-o", "StrictHostKeyChecking=accept-new", "-p", str(port)]
	cmd = ["ssh"] + ssh_opts + [f"{user}@{host}", command]
	click.echo(f"▶ ssh {user}@{host} {command}", err=True)
	return subprocess.call(cmd)


@deploy_server.command("push")
@click.option("--dry-run", is_flag=True, help="Show what would be transferred without doing it")
@click.option("--exclude", multiple=True, default=(".git", "__pycache__", ".venv", "*.pyc"),
              help="Patterns to exclude (can repeat)")
@click.pass_context
def server_push(ctx, dry_run, exclude):
	"""Sync the application to the remote server using rsync."""
	cfg = _load_config(ctx.obj.get("config_path"))
	srv = cfg.get("server")
	if not srv:
		click.echo("❌ No [server] section in .fab-deploy.yml", err=True)
		sys.exit(1)

	host = srv["host"]
	user = srv.get("user", "deploy")
	port = srv.get("port", 22)
	remote_dir = srv["remote_dir"]

	if not shutil.which("rsync"):
		click.echo("❌ rsync not found. Install it or use docker deploy instead.", err=True)
		sys.exit(1)

	cmd = [
		"rsync", "-avz", "--progress",
		"--rsh", f"ssh -p {port} -o StrictHostKeyChecking=accept-new",
	]
	for pat in exclude:
		cmd += ["--exclude", pat]
	if dry_run:
		cmd.append("--dry-run")
	cmd += ["./", f"{user}@{host}:{remote_dir}/"]

	_run(cmd)
	if not dry_run:
		click.echo(f"✅ Synced to {user}@{host}:{remote_dir}")
		click.echo("   Run: flask fab deploy server restart  (to apply)")


@deploy_server.command("start")
@click.pass_context
def server_start(ctx):
	"""Start the application on the remote server."""
	cfg = _load_config(ctx.obj.get("config_path"))
	srv = cfg.get("server", {})
	service = srv.get("service_name")
	custom_cmd = srv.get("start_cmd")

	if custom_cmd:
		_ssh_run(srv, custom_cmd)
	elif service:
		_ssh_run(srv, f"sudo systemctl start {service}")
	else:
		remote_dir = srv.get("remote_dir", "/opt/app")
		venv = srv.get("venv", f"{remote_dir}/.venv")
		_ssh_run(srv, f"cd {remote_dir} && {venv}/bin/gunicorn app:app -b 0.0.0.0:8080 -D")
	click.echo("✅ Start command sent.")


@deploy_server.command("stop")
@click.pass_context
def server_stop(ctx):
	"""Stop the application on the remote server."""
	cfg = _load_config(ctx.obj.get("config_path"))
	srv = cfg.get("server", {})
	service = srv.get("service_name")
	custom_cmd = srv.get("stop_cmd")

	if custom_cmd:
		_ssh_run(srv, custom_cmd)
	elif service:
		_ssh_run(srv, f"sudo systemctl stop {service}")
	else:
		_ssh_run(srv, "pkill -f gunicorn")
	click.echo("✅ Stop command sent.")


@deploy_server.command("restart")
@click.pass_context
def server_restart(ctx):
	"""Restart the application on the remote server."""
	cfg = _load_config(ctx.obj.get("config_path"))
	srv = cfg.get("server", {})
	service = srv.get("service_name")
	custom_cmd = srv.get("restart_cmd")

	if custom_cmd:
		_ssh_run(srv, custom_cmd)
	elif service:
		_ssh_run(srv, f"sudo systemctl restart {service}")
	else:
		# Reinstall deps and restart gunicorn
		remote_dir = srv.get("remote_dir", "/opt/app")
		venv = srv.get("venv", f"{remote_dir}/.venv")
		_ssh_run(srv,
			f"cd {remote_dir} && "
			f"{venv}/bin/pip install -q -r requirements.txt && "
			f"pkill -f gunicorn; "
			f"{venv}/bin/gunicorn app:app -b 0.0.0.0:8080 -D"
		)
	click.echo("✅ Restart command sent.")


@deploy_server.command("status")
@click.pass_context
def server_status(ctx):
	"""Check if the application is running on the remote server."""
	cfg = _load_config(ctx.obj.get("config_path"))
	srv = cfg.get("server", {})
	service = srv.get("service_name")

	if service:
		_ssh_run(srv, f"sudo systemctl status {service} --no-pager")
	else:
		_ssh_run(srv, "pgrep -a gunicorn || echo 'gunicorn not running'")


@deploy_server.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--lines", "-n", default=100, help="Number of lines (default 100)")
@click.pass_context
def server_logs(ctx, follow, lines):
	"""Tail application logs on the remote server."""
	cfg = _load_config(ctx.obj.get("config_path"))
	srv = cfg.get("server", {})
	service = srv.get("service_name")
	log_file = srv.get("log_file")

	if service:
		cmd = f"sudo journalctl -u {service} -n {lines}"
		if follow:
			cmd += " -f"
	elif log_file:
		cmd = f"tail -n {lines} {log_file}"
		if follow:
			cmd = f"tail -n {lines} -f {log_file}"
	else:
		cmd = f"tail -n {lines} /opt/app/logs/app.log 2>/dev/null || journalctl -n {lines}"

	_ssh_run(srv, cmd, pty=follow)


@deploy_server.command("exec")
@click.argument("command", nargs=-1, required=True)
@click.pass_context
def server_exec(ctx, command):
	"""Run an arbitrary command on the remote server."""
	cfg = _load_config(ctx.obj.get("config_path"))
	srv = cfg.get("server", {})
	_ssh_run(srv, " ".join(command))


@deploy_server.command("migrate")
@click.pass_context
def server_migrate(ctx):
	"""Run database migrations on the remote server."""
	cfg = _load_config(ctx.obj.get("config_path"))
	srv = cfg.get("server", {})
	remote_dir = srv.get("remote_dir", "/opt/app")
	venv = srv.get("venv", f"{remote_dir}/.venv")
	_ssh_run(srv, f"cd {remote_dir} && {venv}/bin/flask db upgrade")
	click.echo("✅ Migrations applied.")


@deploy_server.command("shell")
@click.pass_context
def server_shell(ctx):
	"""Open an interactive shell on the remote server."""
	cfg = _load_config(ctx.obj.get("config_path"))
	srv = cfg.get("server", {})
	host = srv["host"]
	user = srv.get("user", "deploy")
	port = srv.get("port", 22)
	os.execvp("ssh", ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=accept-new",
	                   f"{user}@{host}"])


# ─── Convenience top-level commands ──────────────────────────────────────────

@deploy.command("ps")
@click.pass_context
def deploy_ps(ctx):
	"""Show running containers and/or server process status."""
	cfg = _load_config(ctx.obj.get("config_path"))
	docker_cfg = cfg.get("docker", {})
	srv = cfg.get("server")

	compose_file = docker_cfg.get("compose_file", "docker-compose.yml")
	if Path(compose_file).exists():
		click.echo("=== Docker Compose ===")
		subprocess.run(["docker", "compose", "-f", compose_file, "ps"], check=False)

	if srv:
		click.echo("\n=== Remote Server ===")
		service = srv.get("service_name")
		if service:
			_ssh_run(srv, f"sudo systemctl is-active {service} && echo running || echo stopped")
		else:
			_ssh_run(srv, "pgrep -a gunicorn 2>/dev/null || echo 'not running'")
