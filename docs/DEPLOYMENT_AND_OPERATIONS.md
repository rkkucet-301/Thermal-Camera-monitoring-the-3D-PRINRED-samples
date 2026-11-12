# Deployment & Production Operations Guide
### Raspberry Pi 3B, ESP32-S3, and Windows PC Hub

This document covers operational reliability, boot persistence, static networking, firewall rules, and troubleshooting procedures.

---

## 1. Raspberry Pi 3B: SSH Persistence After Reboot

### Will SSH work after the Raspberry Pi reboots?
**YES.** When you executed:
```bash
sudo systemctl enable --now ssh
```
Systemd permanently registered `ssh.service` in the multi-user boot target (`/etc/systemd/system/sshd.service` / `multi-user.target.wants/`). The SSH daemon will start automatically every time the Pi powers on or reboots.

### How to verify SSH is enabled on boot:
```bash
sudo systemctl is-enabled ssh
# Output will report: enabled
```

---

## 2. Preventing IP Address Changes (DHCP Lease vs Static IP)

When the Raspberry Pi reboots, your Wi-Fi router might assign it a different IP address if DHCP dynamic addressing is used. To guarantee you can always connect to `192.168.1.103`:

### Method 1: Router DHCP Static Reservation (Recommended)
1. Log into your Wi-Fi Router Admin Portal (typically `http://192.168.1.1`).
2. Navigate to **DHCP Server** $\to$ **Address Reservation** (or **Static Leases**).
3. Add a reservation using the Pi's Wi-Fi MAC address:
   - **MAC Address:** `b8:27:eb:06:52:f5` *(verified from your `ip a show wlan0`)*
   - **Reserved IP:** `192.168.1.103`
4. Now, regardless of reboots, the Pi will always receive `192.168.1.103`.

### Method 2: Configure Static IP Directly on Raspberry Pi (NetworkManager)
On modern Raspberry Pi OS (Debian 12/13), networking is managed by `NetworkManager`:

```bash
# 1. Identify your Wi-Fi connection name
nmcli connection show

# 2. Set static IPv4 address, gateway, and DNS
sudo nmcli connection modify "TP-Link_A4CC" \
    ipv4.addresses 192.168.1.103/24 \
    ipv4.gateway 192.168.1.1 \
    ipv4.dns "1.1.1.1,8.8.8.8" \
    ipv4.method manual

# 3. Apply changes
sudo nmcli connection up "TP-Link_A4CC"
```

---

## 3. Raspberry Pi Capture Service Auto-Start on Boot

The background capture service `printer_monitor.service` is also enabled on boot:
```bash
sudo systemctl is-enabled printer_monitor.service
# Output: enabled
```

### Useful Service Control Commands:
```bash
# Check running status
sudo systemctl status printer_monitor.service

# Follow real-time capture logs
journalctl -u printer_monitor.service -f -n 50

# Restart service after editing configs
sudo systemctl restart printer_monitor.service

# Stop service temporarily
sudo systemctl stop printer_monitor.service
```

---

## 4. Windows PC Server Firewall Configuration

To ensure the Raspberry Pi (`192.168.1.103`) and the ESP32-S3 can always reach Port 8000 on your PC without Windows Firewall silently dropping packets:

Run this command once in **Windows PowerShell (as Administrator)**:

```powershell
New-NetFirewallRule -DisplayName "3D Printer Telemetry Hub (Port 8000)" `
    -Direction Inbound `
    -LocalPort 8000 `
    -Protocol TCP `
    -Action Allow
```

---

## 5. Dual Camera USB Bandwidth Architecture

### Why Sequential Isolated Capture is Used
The Raspberry Pi 3 Model B routes all 4 USB ports through a single internal SMSC LAN9514 USB 2.0 controller with a shared **480 Mbps total physical bandwidth** and **1.2 A aggregate current limit**.

- If both high-resolution UVC cameras are held open simultaneously with active streaming handles, the Linux UVC driver attempts to reserve periodic isochronous bandwidth endpoints for both cameras, resulting in kernel buffer starvation (`select timeout` or `VIDIOC_DQBUF: No space left on device`).
- The sequential capture engine in `pi_client/capture_service.py` completely solves this:
  1. Opens Cam 1, grabs the hardware MJPEG frame, and immediately calls `cap.release()`.
  2. Waits a 1.0-second stagger delay, allowing the USB controller to tear down endpoints.
  3. Opens Cam 2, grabs the hardware MJPEG frame, and immediately calls `cap.release()`.
- Result: **Zero bandwidth collision, zero current spikes, and zero local SD card wear.**

---

## 6. System Quick-Check Matrix

| Subsystem | Command to Verify | Expected Output |
| :--- | :--- | :--- |
| **Pi Wi-Fi Link** | `iwconfig wlan0` | `Link Quality=70/70 Signal level=-37 dBm` |
| **Pi SSH Service** | `sudo systemctl status ssh` | `Active: active (running)` |
| **Pi Capture Service** | `sudo systemctl status printer_monitor`| `Active: active (running)` |
| **PC Receiver Port** | `Get-NetTCPConnection -LocalPort 8000` | `State: Listen` |
| **Live Web UI** | Browser to `http://localhost:8000` | Full dual camera + thermal dashboard |
