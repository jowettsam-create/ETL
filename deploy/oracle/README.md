# Hosting on Oracle Cloud (free, Sydney)

Temporary home for the web app until NSW Ambulance IT hosts it (see `../../HOSTING.md`).
Result: a normal HTTPS website, e.g. `https://203-0-113-5.sslip.io`, that phones, tablets and
(hopefully) work PCs can open. The server is in Australia so REDCap should accept it.

What runs on the server: the app container (from `../../Dockerfile`) behind **Caddy**, which gets a free
HTTPS certificate automatically. Credentials live only on the server in `/etc/goodsam/goodsam.env`
(root-only). The app won't open without the app password.

---

## 1. Create the Oracle Cloud account (~15 min)

1. Go to **https://www.oracle.com/cloud/free/** → **Start for free**.
2. **Home Region: choose "Australia East (Sydney)"** (or "Australia Southeast (Melbourne)").
   ⚠️ This **can't be changed later**, and free servers only run in your home region.
3. A credit card is needed to verify identity. Always Free resources aren't charged; don't click
   "Upgrade to Pay As You Go".

## 2. Create the server (~10 min)

1. Menu **☰ → Compute → Instances → Create instance**.
2. **Name:** `goodsam-etl`.
3. **Image and shape → Edit:**
   - **Image:** *Change image* → **Canonical Ubuntu 24.04**.
   - **Shape:** *Change shape* → **Ampere → VM.Standard.A1.Flex**, **1 OCPU, 6 GB memory**
     (shows "Always Free-eligible").
     If you get **"Out of capacity"**, either try again later or pick
     **Specialty and previous generation → VM.Standard.E2.1.Micro** (also Always Free; slower but works).
4. **Networking:** leave the defaults (new virtual cloud network, public subnet,
   **Assign a public IPv4 address: Yes**).
5. **Add SSH keys:** **Generate a key pair for me** → **Save private key**. Keep this file safe;
   it's the only way into the server.
6. **Create**. When it shows **Running**, copy the **Public IP address**.

## 3. Open the web ports (~3 min)

1. On the instance page, under **Primary VNIC**, click the **Subnet** link →
   **Security Lists** → the default security list → **Add Ingress Rules**.
2. Add a rule: **Source CIDR** `0.0.0.0/0`, **IP Protocol** TCP, **Destination Port Range** `80`.
3. Add another the same with port `443`.

(The setup script also opens these ports in the server's own firewall.)

## 4. Connect to the server

Easiest: in PowerShell on your PC (replace the key path and IP):
```powershell
ssh -i "$HOME\Downloads\ssh-key-XXXX.key" ubuntu@YOUR.PUBLIC.IP
```
Type `yes` the first time. If it says the key file's permissions are "too open", run this once and try again:
```powershell
icacls "$HOME\Downloads\ssh-key-XXXX.key" /inheritance:r /grant:r "$($env:USERNAME):R"
```

## 5. Install the app (~5–10 min)

On the server (after `ssh`), run:
```bash
curl -fsSL https://raw.githubusercontent.com/jowettsam-create/ETL/main/deploy/oracle/setup.sh -o setup.sh
sudo bash setup.sh
```
It asks for:
- **Web address:** press **Enter** to accept the suggested `…sslip.io` address.
- **GoodSAM username / password** (or API client ID / secret), **REDCap API token**, and an
  **app password** for users. Typing is hidden for the secrets.

It ends with `Done. Open: https://…`.

## 6. Check it

1. Open the address on your phone. You should get the app's password screen.
   (If the browser says the site isn't secure, wait a minute and reload: the certificate is being issued.)
2. Sign in → sidebar → **🔧 Connection check**.
   - **REDCap:** must say *"You do not have permissions to use the API"* (= reached).
     A bare *403 Forbidden* page means REDCap blocks Oracle's servers → tell Claude/IT.
   - **GoodSAM:** `HTTP 401` (= reached).
3. Open the address on a **work PC**. If Zscaler blocks it, note the category it shows.
4. **Daily run → Build only (test)** before the first real upload.

## Day to day

- Update to the latest version from GitHub: `sudo bash /opt/goodsam-etl/deploy/oracle/update.sh`
- Change credentials or the app password: `sudo rm /etc/goodsam/goodsam.env && sudo bash setup.sh`
- See what's running: `sudo docker ps` · App log: `sudo docker logs --tail 50 oracle-app-1`
- It restarts by itself after crashes and server reboots.
- If the GitHub repo is made **private**, the server can't pull updates without a GitHub token. Ask before
  doing that.
- Oracle may reclaim Always Free servers that sit **idle** for 7 days (very low CPU/network). Daily use
  normally prevents this.
