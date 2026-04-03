# Burp ADB Proxy Bridge

A standalone Python script to proxy Android device traffic into Burp Suite over an ADB USB tunnel. 

It replicates the powerful networking capabilities of HTTP Toolkit (such as in-memory system certificate injection via `tmpfs` and mount namespace hijacking on Android 14+), coupled with transparent iptables proxying to forcefully capture rogue traffic (like Flutter apps) into Burp Suite!

## Prerequisites

- **Python 3**
- **ADB** (Available in your PATH)
- **OpenSSL** (Available in your PATH. Windows users: use Git Bash or install OpenSSL)
- A **Rooted** Android Device
- Optional: **Frida & Objection** (`pip install objection`) to automatically bypass strict SSL pinning.

## Installation

1. Copy the script to your machine.
2. Install the optional dependency for the automatic SSL pinning bypass:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### 1. Setup & Start
Start the proxy, inject your Burp Suite CA Certificate, and securely bind your Android device's networking directly to your host PC's Burp proxy.

```bash
python burp_adb_bridge.py start --cert "path/to/burp.der" --port 8080
```

*Note: Ensure your Burp Suite Proxy Listener has **Support invisible proxying** enabled to properly catch the traffic forwarded by the internal iptables rules!*

### 2. Auto-Bypass SSL Pinning (Objection)
If you encounter an app with strict SSL pinning, you can supply its package name! The script will verify the app is running (spawning it automatically if it isn't) and bind `objection` to disable SSL pinning.

```bash
python burp_adb_bridge.py start --cert "burp.der" --port 8080 --objection "com.example.app"
```

### 3. Cleanup & Stop
When you are completely finished testing, gracefully remove all iptables NAT routing and the global proxy configurations.

```bash
python burp_adb_bridge.py stop
```

*(Note: Reboot your Android device to fully flush the in-memory `tmpfs` CA Certificate injection).*

## Acknowledgements 
Core CA injection and ADB tunnel techniques inspired by the excellent open-source work of [HTTP Toolkit](https://httptoolkit.com/).
