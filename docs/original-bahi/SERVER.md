# Getting the most from your Linux box

Your laptop (i3-6006U, 8 GB RAM, Linux Mint) runs everything except the copy of Bahi at each firm:

| Job | Runs on | When |
|---|---|---|
| Lead engine (signal-engine) | Linux box | All the time |
| Bahi, your copy: demos, your own statements, reading scans | Linux box | All the time |
| Nightly backup and re-check of every sample statement | Linux box | 02:30 |
| Windows virtual machine with TallyPrime, for testing | Linux box | Only while testing |
| Building the Windows zip for firms | Linux box | Each release |
| Bahi at a firm | The firm's Windows PC | Office hours |

**Memory on 8 GB:**

| | RAM |
|---|---|
| Linux Mint desktop | about 1.5 GB |
| Lead engine | about 0.2 GB |
| Bahi | 0.2 GB idle, up to about 0.6 GB while reading a scan |
| Windows 10 VM with TallyPrime | 3.5 to 4 GB, only while you test |
| Left over | about 1.5 GB |

It fits. Turn on compressed swap so a spike slows things down instead of freezing them: `sudo apt install zram-config`, then reboot.

## 1. Keep the laptop running

- **Closing the lid shouldn't stop it.** Edit `/etc/systemd/logind.conf` with `sudo nano /etc/systemd/logind.conf` and set:
  ```
  HandleLidSwitch=ignore
  HandleLidSwitchExternalPower=ignore
  ```
  Then reboot.
- **Turn off sleep:**
  ```bash
  sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
  ```
- **Protect the battery.** A battery kept at 100% for months swells and wears out. If your laptop supports charge limits (many ThinkPads and some others do):
  1. Install TLP: `sudo apt install tlp`.
  2. Set these two lines in `/etc/tlp.conf`:
     ```
     START_CHARGE_THRESH_BAT0=40
     STOP_CHARGE_THRESH_BAT0=80
     ```
  3. Run `sudo tlp start`.
- **Heat:** keep it on a hard surface with the vents clear. The i3-6006U is a 15 W chip and stays cool at idle.
- **Security updates:** `sudo apt install unattended-upgrades`.

## 2. Run Bahi as a service

```bash
systemctl --user enable --now bahi bahi-nightly.timer
sudo loginctl enable-linger $USER      # keep it running when you're logged out
journalctl --user -u bahi -f           # watch the log
```

Every night at 02:30 it does two things:
- **Backs up** the database to `~/bahi-data/data/backups`, keeping the last 14.
- **Runs `bahi lab`**, which re-reads every statement in the corpus and compares it with the known answer. The report is at `~/bahi-data/logs/lab.html`.

Put real statements in a private corpus folder (yours, or a firm's with permission) and point `[lab] corpus` in `bahi.toml` at it. Then a change that fixes one bank can't quietly break another.

## 3. Open it from your phone and MacBook

In `~/bahi-data/bahi.toml`:

```toml
[server]
host = "0.0.0.0"
password = "a long password you don't use anywhere else"
```

Restart Bahi with `systemctl --user restart bahi`. On your Wi-Fi, open `http://<laptop IP>:8765` and log in with user `admin`. `hostname -I` shows the IP.

Allow only your home network and Tailscale through the firewall:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 8765 proto tcp
sudo ufw allow in on tailscale0 to any port 8765 proto tcp
sudo ufw enable
```

**Away from home**, for example at a CA's office:
1. Install Tailscale on the laptop, your MacBook and your phone. On the laptop:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
2. Open `http://<laptop Tailscale IP>:8765`.

Traffic is encrypted between your devices, and nothing is opened to the internet. Don't forward port 8765 on your router.

Use this copy for demos and your own data. A firm's real statements belong on the firm's PC.

## 4. Watched folders (optional)

Set `[watch] enabled = true` and restart Bahi.
- Make a folder per client in `~/bahi-data/inbox/`, named exactly like the client.
- Files dropped there are imported automatically, then moved to `done/`, or to `failed/` with a note explaining why.

For a firm that would rather send PDFs than install anything, pair this with Syncthing. It keeps a folder in sync between their PC and your laptop with no cloud in between. Get the firm's written agreement first: you're then holding their clients' data, which the DPDP Act treats as personal data.

## 5. A Windows VM with TallyPrime, for testing

1. Install VirtualBox: `sudo apt install virtualbox`. Skip the Extension Pack: its licence doesn't cover business use without paying, and you don't need it.
2. Download the Windows 10 ISO from Microsoft and create a VM:
   - Windows 10 (64-bit), 4 GB RAM, 2 CPUs, 50 GB disk.
   - Windows needs a licence.
   - Windows 10 no longer gets security updates, so use this VM only for testing.
3. Inside the VM:
   1. Install TallyPrime from tallysolutions.com and choose Educational mode.
   2. Create a test company.
   3. In **F1 (Help) > Settings > Connectivity**, set *TallyPrime acts as* to Server or Both, port 9000.
   4. Allow it through Windows Firewall when asked.
4. In VirtualBox, open **Settings > Network > Adapter 1 (NAT) > Port Forwarding** and forward host port **9900** to guest port **9000**.
5. In `~/bahi-data/bahi.toml` set:
   ```toml
   [tally]
   host = "127.0.0.1"
   port = 9900
   edu_mode = true
   ```
   Restart Bahi and run `bahi tally-check`.
6. Work through [TALLY-TEST.md](TALLY-TEST.md). Set `edu_mode = false` when you finish.

Start the VM only when you test. It's the one thing here that needs half your RAM.

## 6. Build releases for firms

```bash
bahi build-windows --out ~/bahi-dist --cache ~/.cache/bahi-build
```

Copy the zip to a USB stick, or share it. Keep the previous zip too, so you can roll a firm back if a new version misbehaves. To update a firm, replace the `app` and `python` folders in `C:\Bahi`. Leave `data` and `bahi.toml` alone.

## 7. Backups off the box

The nightly backup protects against mistakes, not a dead laptop. Once a week, run this on the MacBook to copy the backups over:

```bash
rsync -a rudra@<laptop IP>:bahi-data/data/backups/ ~/bahi-backups/
```
