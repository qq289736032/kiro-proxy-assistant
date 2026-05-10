"""Kiro Proxy Assistant CLI 入口。"""

import click
import subprocess
import sys
import os
import signal
from pathlib import Path
from . import __version__


PID_FILE = Path.home() / ".kiro-proxy" / "proxy.pid"
MITMPROXY_SCRIPT = Path(__file__).parent / "kiro_mitmproxy.py"


@click.group(invoke_without_command=True)
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx):
    """Kiro Proxy Assistant - Route Kiro AI requests to LiteLLM."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.option("--port", default=9080, help="Proxy listen port")
def start(port):
    """Start the Kiro proxy server."""
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            click.echo(f"✗ Proxy already running (PID {pid})")
            return
        except OSError:
            PID_FILE.unlink()

    # 启动前检查端口是否被占用
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            click.echo(f"✗ Port {port} is already in use.")
            click.echo(f"  Run: kill -9 $(lsof -ti:{port})")
            return

    click.echo(f"Starting Kiro proxy on port {port}...")

    log_file = Path.home() / ".kiro-proxy" / "proxy.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # 找到 venv 中的 mitmdump 可执行文件
    mitmdump_bin = Path(sys.executable).parent / "mitmdump"
    if not mitmdump_bin.exists():
        import shutil
        mitmdump_path = shutil.which("mitmdump")
        if not mitmdump_path:
            click.echo("✗ mitmdump not found. Install with: pip install mitmproxy")
            return
        mitmdump_bin = Path(mitmdump_path)

    cmd = [
        str(mitmdump_bin),
        "-s", str(MITMPROXY_SCRIPT),
        "--listen-port", str(port),
        "--ssl-insecure",
        "--set", "connection_strategy=lazy",
    ]

    try:
        with open(log_file, "a") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf)

        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(proc.pid))

        # 等待 2 秒后验证进程是否真正存活
        import time
        time.sleep(2)
        try:
            os.kill(proc.pid, 0)
        except OSError:
            # 进程已退出，读取日志末尾显示错误
            PID_FILE.unlink(missing_ok=True)
            click.echo(f"✗ Proxy failed to start. Last log lines:")
            try:
                lines = log_file.read_text().splitlines()
                for line in lines[-10:]:
                    click.echo(f"  {line}")
            except Exception:
                pass
            return

        click.echo(f"✓ Proxy started (PID {proc.pid})")
        click.echo(f"  Listening on: http://127.0.0.1:{port}")
        click.echo(f"  Log file:     {log_file}")
        click.echo(f"")
        click.echo(f"  Configure Kiro: Settings → HTTP Proxy → http://127.0.0.1:{port}")
        click.echo(f"  View logs:      kiro-proxy logs")
        click.echo(f"  View stats:     kiro-proxy stats")
    except Exception as e:
        click.echo(f"✗ Failed to start: {e}")


@cli.command()
def stop():
    """Stop the Kiro proxy server."""
    if not PID_FILE.exists():
        click.echo("✗ Proxy is not running")
        return

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink()
        click.echo(f"✓ Proxy stopped (PID {pid})")
    except OSError:
        PID_FILE.unlink()
        click.echo("✓ Proxy was not running, cleaned up PID file")


@cli.command()
def status():
    """Show proxy server status."""
    if not PID_FILE.exists():
        click.echo("Status: stopped")
        return

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, 0)
        click.echo(f"Status: running (PID {pid})")
    except OSError:
        PID_FILE.unlink()
        click.echo("Status: stopped (stale PID file cleaned)")


@cli.command()
@click.pass_context
def restart(ctx):
    """Restart the Kiro proxy server."""
    ctx.invoke(stop)
    ctx.invoke(start)


@cli.command()
def logs():
    """Show proxy logs (tail -f)."""
    log_file = Path.home() / ".kiro-proxy" / "proxy.log"
    if not log_file.exists():
        click.echo(f"✗ Log file not found: {log_file}")
        click.echo("  Start the proxy first: kiro-proxy start")
        return

    click.echo(f"Tailing {log_file} (Ctrl+C to stop)...")
    click.echo("─" * 50)
    try:
        import subprocess
        subprocess.run(["tail", "-f", str(log_file)])
    except KeyboardInterrupt:
        pass


@cli.command()
def setup():
    """Show Kiro proxy configuration instructions."""
    click.echo("Kiro Proxy Setup Instructions")
    click.echo("─" * 40)
    click.echo("")
    click.echo("1. Start the proxy:")
    click.echo("   kiro-proxy start")
    click.echo("")
    click.echo("2. Configure Kiro IDE:")
    click.echo("   • Open Kiro Settings (Cmd+,)")
    click.echo("   • Search for 'proxy'")
    click.echo("   • Set HTTP Proxy to: http://127.0.0.1:9080")
    click.echo("")
    click.echo("3. Configure API key (one of):")
    click.echo("   • Edit config.yaml: set litellm.api_key")
    click.echo("   • Set env var: export LITELLM_API_KEY=sk-...")
    click.echo("")
    click.echo("4. Verify it's working:")
    click.echo("   • Send a message in Kiro")
    click.echo("   • Check logs: kiro-proxy logs")
    click.echo("   • Check stats: kiro-proxy stats")


@cli.command()
def stats():
    """Show proxy statistics."""
    from .stats_collector import StatsCollector
    collector = StatsCollector()
    s = collector.get_stats()

    click.echo("Kiro Proxy Statistics")
    click.echo("─" * 30)
    click.echo(f"Total Requests:  {s['total_requests']}")
    click.echo(f"Total Responses: {s['total_responses']}")
    click.echo(f"Errors:          {s['total_errors']}")
    click.echo(f"Avg Latency:     {s['average_latency']:.1f}ms")
    click.echo("")
    click.echo("Model Usage:")
    for model, count in s.get("model_usage", {}).items():
        click.echo(f"  {model}: {count}")


if __name__ == "__main__":
    cli()
