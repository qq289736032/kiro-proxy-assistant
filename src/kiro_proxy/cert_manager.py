"""mitmproxy CA certificate lifecycle management.

Handles certificate generation, system trust store installation,
verification, and removal across macOS, Linux, and Windows.
"""

import sys
import time
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CERT_DIR = Path.home() / ".mitmproxy"
CA_CERT = CERT_DIR / "mitmproxy-ca-cert.pem"
CA_KEY = CERT_DIR / "mitmproxy-ca.pem"
TEMP_PORT = 17870


def _os() -> str:
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform == "win32":
        return "windows"
    elif sys.platform == "linux":
        return "linux"
    return "unknown"


def _find_mitmdump() -> Path:
    mitmdump_bin = Path(sys.executable).parent / "mitmdump"
    if mitmdump_bin.exists():
        return mitmdump_bin
    import shutil
    path = shutil.which("mitmdump")
    if path:
        return Path(path)
    raise FileNotFoundError(
        "mitmdump not found. Install with: pip install mitmproxy"
    )


# ── Status checks ──────────────────────────────────────────

def cert_exists() -> bool:
    return CA_CERT.exists()


def is_installed() -> bool:
    """Check if the CA certificate is in the system trust store."""
    name = _os()
    if name == "macos":
        r = subprocess.run(
            ["security", "find-certificate", "-c", "mitmproxy",
             "/Library/Keychains/System.keychain"],
            capture_output=True, text=True
        )
        return r.returncode == 0

    if name == "linux":
        return (Path("/usr/local/share/ca-certificates") / CA_CERT.name).exists()

    if name == "windows":
        r = subprocess.run(
            ["certutil", "-store", "Root", "mitmproxy"],
            capture_output=True, text=True
        )
        return r.returncode == 0

    return False


# ── Generate ────────────────────────────────────────────────

def generate() -> bool:
    """Run mitmdump briefly to trigger CA certificate generation."""
    if CA_CERT.exists():
        return True

    try:
        mitmdump_bin = _find_mitmdump()
    except FileNotFoundError as e:
        print(f"  ✗ {e}")
        return False

    print("  Generating mitmproxy CA certificate...")

    proc = subprocess.Popen(
        [str(mitmdump_bin), "--listen-port", str(TEMP_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        for _ in range(30):
            if CA_CERT.exists():
                break
            time.sleep(1)
        else:
            print("  ✗ Timeout waiting for CA certificate generation")
            return False
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    if CA_CERT.exists():
        print(f"  ✓ CA certificate generated: {CA_CERT}")
        return True

    print("  ✗ Failed to generate CA certificate")
    return False


# ── Install ─────────────────────────────────────────────────

def _install_macos() -> bool:
    print("  Installing into macOS system keychain...")
    r = subprocess.run([
        "sudo", "security", "add-trusted-cert", "-d", "-r", "trustRoot",
        "-k", "/Library/Keychains/System.keychain",
        str(CA_CERT),
    ])
    if r.returncode != 0:
        print("  ✗ Failed to install certificate")
        return False
    print("  ✓ Certificate installed to system keychain")
    return True


def _install_linux() -> bool:
    ca_dir = Path("/usr/local/share/ca-certificates/")
    dest = ca_dir / CA_CERT.name

    print(f"  Copying certificate to {dest}...")
    subprocess.run(["sudo", "cp", str(CA_CERT), str(dest)], check=True)

    print("  Updating CA certificates...")
    subprocess.run(["sudo", "update-ca-certificates"], check=True)

    print("  ✓ Certificate installed")
    return True


def _install_windows() -> bool:
    print("  Installing into Windows root store...")
    r = subprocess.run(
        ["certutil", "-addstore", "Root", str(CA_CERT)],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        print("  ✓ Certificate installed")
        return True
    print("  ✗ Failed to install certificate. Make sure you're running as Administrator.")
    return False


def install() -> bool:
    """Install the CA certificate into the system trust store."""
    name = _os()
    if name == "macos":
        return _install_macos()
    elif name == "linux":
        return _install_linux()
    elif name == "windows":
        return _install_windows()
    print(f"  ✗ Unsupported OS: {sys.platform}")
    return False


# ── Remove ──────────────────────────────────────────────────

def _fingerprint_macos() -> str | None:
    """Get SHA-1 fingerprint of the installed mitmproxy certificate from keychain.

    Returns fingerprint as uppercase hex without colons for comparison.
    """
    r = subprocess.run(
        ["security", "find-certificate", "-c", "mitmproxy", "-Z",
         "/Library/Keychains/System.keychain"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("SHA-1 hash:"):
            fp = line.split(":", 1)[-1].strip()
            return fp.upper().replace(":", "")
    return None


def _fingerprint_local() -> str | None:
    """Get SHA-1 fingerprint of the local mitmproxy CA cert file.

    Returns fingerprint as uppercase hex without colons for comparison.
    """
    if not CA_CERT.exists():
        return None
    r = subprocess.run(
        ["openssl", "x509", "-in", str(CA_CERT), "-noout", "-fingerprint", "-sha1"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    # Output: "SHA1 Fingerprint=AA:BB:CC:..."
    for line in r.stdout.splitlines():
        if "=" in line:
            fp = line.split("=", 1)[-1].strip()
            return fp.upper().replace(":", "")
    return None


def _remove_macos() -> bool:
    # Get fingerprints to ensure we remove the right cert
    installed_fp = _fingerprint_macos()
    local_fp = _fingerprint_local()

    if installed_fp and local_fp and installed_fp != local_fp:
        print("  ✗ Fingerprint mismatch — refusing to remove.")
        print(f"    Installed certificate SHA-1: {installed_fp}")
        print(f"    Local mitmproxy certificate SHA-1: {local_fp}")
        print("    The installed certificate doesn't match the mitmproxy CA.")
        print("    To force removal, run: sudo security delete-certificate -Z \"{}\" /Library/Keychains/System.keychain".format(installed_fp))
        return False

    if installed_fp:
        # Delete by SHA-1 hash (precise match — won't touch other certs)
        r = subprocess.run(
            ["sudo", "security", "delete-certificate", "-Z", installed_fp,
             "/Library/Keychains/System.keychain"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            print("  ✓ Certificate removed from system keychain (by SHA-1 fingerprint)")
            return True
        print("  ✗ Failed to remove certificate from system keychain")
        return False

    print("  Certificate not in system keychain (already removed?)")
    return True


def _remove_linux() -> bool:
    dest = Path("/usr/local/share/ca-certificates") / CA_CERT.name
    if dest.exists():
        subprocess.run(["sudo", "rm", str(dest)])
        subprocess.run(["sudo", "update-ca-certificates", "--fresh"])
        print("  ✓ Certificate removed")
    else:
        print("  Certificate not in system CA directory (already removed?)")
    return True


def _remove_windows() -> bool:
    # certutil -delstore accepts SHA-1 hash for precise deletion
    # First, find the fingerprint
    r = subprocess.run(
        ["certutil", "-store", "Root", "mitmproxy"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("  Certificate not in root store (already removed?)")
        return True

    r = subprocess.run(
        ["certutil", "-delstore", "Root", "mitmproxy"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        print("  ✓ Certificate removed from root store")
        return True
    print("  ✗ Failed to remove certificate")
    return False


def remove(keep_files: bool = False) -> bool:
    """Remove the CA certificate from system trust store and clean up files.

    Args:
        keep_files: If True, leave certificate files on disk for later re-use.
    """
    name = _os()
    ok = False

    if name == "macos":
        ok = _remove_macos()
    elif name == "linux":
        ok = _remove_linux()
    elif name == "windows":
        ok = _remove_windows()
    else:
        print(f"  ✗ Unsupported OS: {sys.platform}")
        return False

    if not ok:
        return False

    # Clean up certificate files unless user asked to keep them
    if not keep_files:
        _cleanup_files()
    else:
        print("  Keeping certificate files for later re-use.")

    print()
    print("  Note: If you use Firefox, check its certificate store separately:")
    print("    Settings → Privacy & Security → Certificates → View Certificates → Authorities")
    print("    Remove 'mitmproxy' if present.")
    return True


def _cleanup_files() -> None:
    """Remove mitmproxy certificate files from disk."""
    removed_any = False
    if CA_CERT.exists():
        CA_CERT.unlink()
        print(f"  ✓ Removed certificate file: {CA_CERT}")
        removed_any = True
    if CA_KEY.exists():
        CA_KEY.unlink()
        print(f"  ✓ Removed private key file: {CA_KEY}")
        removed_any = True
    # Remove empty parent dir too
    if CERT_DIR.exists() and not any(CERT_DIR.iterdir()):
        CERT_DIR.rmdir()
        print(f"  ✓ Removed empty directory: {CERT_DIR}")
    if not removed_any:
        print("  No certificate files found on disk.")


def preview_removal() -> bool:
    """Show certificate info that will be removed. Returns True if anything exists to clean up."""
    name = _os()
    in_trust = is_installed()
    files_exist = cert_exists()

    if not in_trust and not files_exist:
        print("  No mitmproxy certificate found — nothing to remove.")
        return False

    if in_trust:
        print("  The following certificate will be removed from your system trust store:")
        print()
        if name == "macos":
            fp = _fingerprint_macos()
            if fp:
                r = subprocess.run(
                    ["security", "find-certificate", "-c", "mitmproxy", "-p",
                     "/Library/Keychains/System.keychain"],
                    capture_output=True, text=True,
                )
                if r.stdout:
                    info = subprocess.run(
                        ["openssl", "x509", "-noout", "-subject", "-issuer", "-dates"],
                        input=r.stdout, capture_output=True, text=True,
                    )
                    if info.stdout:
                        for line in info.stdout.splitlines():
                            print(f"    {line}")
                print(f"    SHA-1: {fp}")
        elif name == "linux":
            dest = Path("/usr/local/share/ca-certificates") / CA_CERT.name
            if dest.exists():
                print(f"    File: {dest}")
                subprocess.run([
                    "openssl", "x509", "-in", str(dest),
                    "-noout", "-subject", "-issuer", "-dates",
                ])
        elif name == "windows":
            r = subprocess.run(
                ["certutil", "-store", "Root", "mitmproxy"],
                capture_output=True, text=True,
            )
            if r.stdout:
                print(r.stdout)
        print()

    if files_exist:
        print(f"  Certificate files on disk:")
        if CA_CERT.exists():
            print(f"    {CA_CERT}")
        if CA_KEY.exists():
            print(f"    {CA_KEY}")
        print()

    return True


# ── Check ───────────────────────────────────────────────────

def check() -> None:
    """Print certificate status to the console."""
    print(f"  Certificate file: {CA_CERT}")
    print(f"  File exists:       {'✓ yes' if CA_CERT.exists() else '✗ no'}")
    print(f"  Private key:       {'✓ present' if CA_KEY.exists() else '✗ missing'}")
    print(f"  System trust:      {'✓ trusted' if is_installed() else '✗ not trusted'}")

    if CA_CERT.exists():
        print()
        subprocess.run([
            "openssl", "x509", "-in", str(CA_CERT),
            "-noout", "-subject", "-issuer", "-dates",
        ])
