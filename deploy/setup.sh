#!/usr/bin/env bash
# VM-side one-shot setup for pe-runner on Oracle Cloud Always Free (Ubuntu/ARM).
# Idempotent: safe to re-run (also used to update to the latest code).
#
#   curl -fsSL https://raw.githubusercontent.com/TrueRyoB/pe-runner/main/deploy/setup.sh | bash
#   # or: git clone ... && cd pe-runner && bash deploy/setup.sh
#
# After this runs once, put your .env in the repo dir, then:
#   .venv/bin/python tools/check_pe.py      # verify PE auth from THIS server
#   sudo systemctl enable --now pe-runner   # start & keep running 24/7
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/TrueRyoB/pe-runner.git}"
APP_DIR="${APP_DIR:-$HOME/pe-runner}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"

echo "==> Installing system packages (python venv, git)"
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git

echo "==> Fetching code into $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> Creating venv and installing dependencies (aarch64 wheels)"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -q -r requirements.txt

echo "==> Installing systemd unit (user=$SERVICE_USER, dir=$APP_DIR)"
sed -e "s|/home/ubuntu/pe-runner|$APP_DIR|g" \
    -e "s|^User=ubuntu$|User=$SERVICE_USER|" \
    deploy/pe-runner.service | sudo tee /etc/systemd/system/pe-runner.service >/dev/null
sudo systemctl daemon-reload

echo
echo "==> Done. Next steps:"
if [ ! -f "$APP_DIR/.env" ]; then
  echo "   1) Copy your .env here:  scp .env <user>@<vm-ip>:$APP_DIR/.env"
  echo "      (contains Discord token + PE cookie; never commit it)"
else
  echo "   1) .env already present ✓"
fi
echo "   2) Verify PE auth from this server:  .venv/bin/python tools/check_pe.py"
echo "   3) Start the bot 24/7:               sudo systemctl enable --now pe-runner"
echo "   4) Watch logs:                       journalctl -u pe-runner -f"
