import argparse
import subprocess
import sys
import os
import time

def run_cmd(cmd, check=True, capture_output=True):
    print(f"[*] Running: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, check=check, capture_output=capture_output, text=True)
        if res.stdout and capture_output:
            print(f"    {res.stdout.strip()}")
        return res.stdout.strip() if capture_output else ""
    except subprocess.CalledProcessError as e:
        print(f"[!] Error running command: {' '.join(cmd)}")
        if getattr(e, 'stderr', None):
            print(f"{e.stderr.strip()}")
        if check:
            sys.exit(1)
        return False

def check_device():
    devices = run_cmd(['adb', 'devices']).split('\n')[1:]
    connected = [d for d in devices if '\tdevice' in d]
    if not connected:
        print("[!] No ADB devices connected.")
        sys.exit(1)
    print("[+] Found connected ADB device.")

def get_cert_hash(cert_path):
    print(f"[*] Extracting subject hash from {cert_path}")
    
    # Try reading as PEM first
    try:
        res = subprocess.run(['openssl', 'x509', '-inform', 'PEM', '-subject_hash_old', '-in', cert_path, '-noout'], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except subprocess.CalledProcessError:
        pass
    except FileNotFoundError:
        print("[!] ERROR: OpenSSL is not installed or not in your system PATH!")
        print("[!] The script requires OpenSSL to extract the certificate hash. Please install OpenSSL for Windows or run the script using Git Bash.")
        sys.exit(1)
        
    # Try reading as DER
    print("[*] Failed reading as PEM, trying as DER format")
    try:
        # Convert DER to PEM temporarily
        pem_path = cert_path + ".pem"
        subprocess.run(['openssl', 'x509', '-inform', 'DER', '-in', cert_path, '-out', pem_path], check=True)
        res = subprocess.run(['openssl', 'x509', '-inform', 'PEM', '-subject_hash_old', '-in', pem_path, '-noout'], capture_output=True, text=True, check=True)
        return res.stdout.strip(), pem_path
    except subprocess.CalledProcessError as e:
        print(f"[!] Failed to parse certificate. Ensure OpenSSL is installed and the cert is valid. Error: {e}")
        sys.exit(1)
        
def install_cert(cert_path, cert_hash):
    filename = f"{cert_hash}.0"
    remote_tmp = f"/data/local/tmp/{filename}"
    print(f"[*] Pushing cert to {remote_tmp}")
    run_cmd(['adb', 'push', cert_path, remote_tmp])
    
    script = f"""
    set -e
    echo "[*] Injecting certificate"

    mkdir -p /data/local/tmp/htk-ca-copy
    chmod 700 /data/local/tmp/htk-ca-copy
    rm -rf /data/local/tmp/htk-ca-copy/*

    if [ -d "/apex/com.android.conscrypt/cacerts" ]; then
        cp /apex/com.android.conscrypt/cacerts/* /data/local/tmp/htk-ca-copy/
    else
        cp /system/etc/security/cacerts/* /data/local/tmp/htk-ca-copy/
    fi

    mount -t tmpfs tmpfs /system/etc/security/cacerts
    mv /data/local/tmp/htk-ca-copy/* /system/etc/security/cacerts/
    cp {remote_tmp} /system/etc/security/cacerts/{filename}

    chown root:root /system/etc/security/cacerts/*
    chmod 644 /system/etc/security/cacerts/*
    chcon u:object_r:system_file:s0 /system/etc/security/cacerts/ 2>/dev/null || true
    chcon u:object_r:system_file:s0 /system/etc/security/cacerts/* 2>/dev/null || true

    echo "[*] System cacerts setup completed"

    if [ -d "/apex/com.android.conscrypt/cacerts" ]; then
        echo "[*] Injecting certificates into APEX cacerts"
        mount --bind /system/etc/security/cacerts /apex/com.android.conscrypt/cacerts
        
        ZYGOTE_PID=$(pidof zygote || true)
        ZYGOTE64_PID=$(pidof zygote64 || true)
        Z_PIDS="$ZYGOTE_PID $ZYGOTE64_PID"

        for Z_PID in $Z_PIDS; do
            if [ -n "$Z_PID" ]; then
                nsenter --mount=/proc/$Z_PID/ns/mnt -- /bin/mount --bind /system/etc/security/cacerts /apex/com.android.conscrypt/cacerts
            fi
        done

        APP_PIDS=$(echo $Z_PIDS | xargs -n1 ps -o 'PID' -P | grep -v PID || true)
        for PID in $APP_PIDS; do
            nsenter --mount=/proc/$PID/ns/mnt -- /bin/mount --bind /system/etc/security/cacerts /apex/com.android.conscrypt/cacerts &
        done
        wait
    fi

    rm -r /data/local/tmp/htk-ca-copy
    echo "[+] System cert successfully injected"
    """
    
    script_path = "/data/local/tmp/inject_cert.sh"
    with open("inject_cert.sh", "w", newline='\n') as f:
        f.write(script)
        
    run_cmd(['adb', 'push', 'inject_cert.sh', script_path])
    os.remove("inject_cert.sh")
    
    print("[*] Running injection script as root...")
    run_cmd(['adb', 'shell', 'su', '-c', f'sh {script_path}'])
    
def setup_routing(port):
    print(f"[*] Setting up ADB Reverse Tunnel on port {port}")
    run_cmd(['adb', 'reverse', f'tcp:{port}', f'tcp:{port}'])
    
    print(f"[*] Setting global HTTP proxy to 127.0.0.1:{port}")
    run_cmd(['adb', 'shell', 'settings', 'put', 'global', 'http_proxy', f'127.0.0.1:{port}'])
    
    print("[*] Setting up Iptables transparent proxy (Option A)")
    # Enable route_localnet so that DNAT to 127.0.0.1 works
    run_cmd(['adb', 'shell', 'su', '-c', 'sysctl -w net.ipv4.conf.all.route_localnet=1'], check=False)
    
    iptables_script = f"""
    iptables -t nat -A OUTPUT -p tcp --dport 80 -j DNAT --to-destination 127.0.0.1:{port}
    iptables -t nat -A OUTPUT -p tcp --dport 443 -j DNAT --to-destination 127.0.0.1:{port}
    echo "[+] Iptables rules injected"
    """
    
    routing_path = "/data/local/tmp/setup_routing.sh"
    with open("setup_routing.sh", "w", newline='\n') as f:
        f.write(iptables_script)
        
    run_cmd(['adb', 'push', 'setup_routing.sh', routing_path])
    os.remove("setup_routing.sh")
    
    run_cmd(['adb', 'shell', 'su', '-c', f'sh {routing_path}'])
    print(f"[!] IMPORTANT: For transparent proxying (iptables) to work, you MUST enable 'Support invisible proxying' in your Burp Suite Proxy Listener settings for port {port}!")

def stop_routing(port):
    print("[*] Removing global HTTP proxy")
    run_cmd(['adb', 'shell', 'settings', 'put', 'global', 'http_proxy', ':0'])
    
    print(f"[*] Removing ADB Reverse Tunnel on port {port}")
    run_cmd(['adb', 'reverse', '--remove', f'tcp:{port}'], check=False)
    
    print("[*] Removing Iptables transparent proxy rules")
    iptables_script = f"""
    iptables -t nat -D OUTPUT -p tcp --dport 80 -j DNAT --to-destination 127.0.0.1:{port} || true
    iptables -t nat -D OUTPUT -p tcp --dport 443 -j DNAT --to-destination 127.0.0.1:{port} || true
    echo "[+] Iptables rules removed"
    """
    routing_path = "/data/local/tmp/remove_routing.sh"
    with open("remove_routing.sh", "w", newline='\n') as f:
        f.write(iptables_script)
        
    run_cmd(['adb', 'push', 'remove_routing.sh', routing_path])
    os.remove("remove_routing.sh")
    run_cmd(['adb', 'shell', 'su', '-c', f'sh {routing_path}'])
    
    print("\n[+] Routing stopped.")
    print("[!] Note: The certificate is still temporarily injected into the system limits. Reboot the device to remove it completely.")

def run_objection(package):
    print(f"\n[*] Starting Objection against {package} to disable SSL pinning...")
    print("[!] Ensure you have started frida-server on the device!")
    
    # Check if app is running
    pid = run_cmd(['adb', 'shell', 'pidof', package], check=False, capture_output=True)
    if not pid:
        print(f"[*] App {package} is not running. Spawning it now...")
        # Use monkey to reliably trigger the app's default launcher intent
        run_cmd(['adb', 'shell', 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1'], check=False, capture_output=False)
        time.sleep(3) # Give it a moment to boot up before we hook
    else:
        print(f"[*] App is already running with PID: {pid}")
        
    try:
        # We don't capture output here so the user can interact with the objection prompt directly if needed,
        # but we also pass the explicit explore command to auto-run the pinning script.
        subprocess.run(['objection', '-g', package, 'explore', '-s', 'android sslpinning disable'])
    except Exception as e:
        print(f"[!] Errored running objection: {e}")

def main():
    parser = argparse.ArgumentParser(description="Inject Burp CA into Android Root and setup ADB reverse proxying.")
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Start command
    parser_start = subparsers.add_parser('start', help='Setup the proxy and inject the certificate')
    parser_start.add_argument('--cert', required=True, help="Path to your Burp Suite CA certificate (DER or PEM formatting)")
    parser_start.add_argument('--port', type=int, default=8080, help="Burp Suite Proxy port (default 8080)")
    parser_start.add_argument('--objection', help="Optional: Package name to launch with Objection to bypass strict SSL pinning")

    # Stop command
    parser_stop = subparsers.add_parser('stop', help='Remove proxy settings and routing')
    parser_stop.add_argument('--port', type=int, default=8080, help="Burp Suite Proxy port (default 8080)")

    args = parser.parse_args()

    check_device()
    
    if args.command == 'start':
        # Strip hidden unicode characters (like \u202a from Windows copy-paste)
        cert_path = args.cert.strip('\u202a\u202b\u202c\"\'')
        
        # Try handling cert format
        result = get_cert_hash(cert_path)
        if isinstance(result, tuple):
            cert_hash, cert_to_push = result
        else:
            cert_hash = result
            cert_to_push = cert_path
            
        print(f"[+] Identified Cert Hash: {cert_hash}")
        
        install_cert(cert_to_push, cert_hash)
        setup_routing(args.port)
        
        if cert_to_push != cert_path and os.path.exists(cert_to_push):
            os.remove(cert_to_push) # Clean up temp pem file
            
        print(f"\n[+] All Done! The device is now routing traffic to 127.0.0.1:{args.port}.")
        
        if args.objection:
            run_objection(args.objection)

    elif args.command == 'stop':
        stop_routing(args.port)

if __name__ == "__main__":
    main()
