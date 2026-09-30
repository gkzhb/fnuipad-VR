#!/bin/bash
# Setup script for VR Gamepad on Linux
# Run with: sudo ./setup.sh

set -e

if [ -e /etc/NIXOS ]; then
    echo "On NixOS use nix develop and declarative uinput rules; see README.md."
    exit 1
fi

echo "VR Gamepad Setup"
echo "================"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo $0"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER="${SUDO_USER:-$USER}"

echo "Setting up for user: $ACTUAL_USER"
echo

# 1. Load uinput module
echo "[1/5] Loading uinput kernel module..."
modprobe uinput
echo "  Done"

# 2. Make it load on boot
echo "[2/5] Adding uinput to modules-load.d..."
echo "uinput" > /etc/modules-load.d/uinput.conf
echo "  Done"

# 3. Create udev rule for uinput permissions
echo "[3/5] Creating udev rule for /dev/uinput..."
cat > /etc/udev/rules.d/99-uinput.rules << 'EOF'
# Allow users in input group to access uinput
KERNEL=="uinput", GROUP="input", MODE="0660"

# Tag virtual gamepads as joysticks for SDL/Wine compatibility
SUBSYSTEM=="input", ATTRS{name}=="VR Gamepad*", ENV{ID_INPUT_JOYSTICK}="1"
SUBSYSTEM=="input", ATTRS{name}=="Test Gamepad*", ENV{ID_INPUT_JOYSTICK}="1"
EOF
echo "  Done"

# 4. Add user to input group
echo "[4/5] Adding $ACTUAL_USER to input group..."
usermod -aG input "$ACTUAL_USER"
echo "  Done"

# 5. Reload udev rules
echo "[5/5] Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger
echo "  Done"

echo
echo "Setup complete!"
echo
echo "IMPORTANT: You need to log out and back in for group changes to take effect."
echo
echo "To verify setup:"
echo "  1. Log out and log back in"
echo "  2. Run: groups | grep input"
echo "  3. Run: ls -la /dev/uinput"
echo "  4. Run: python test_gamepad.py"
echo

# Install Python dependencies
echo "Installing Python dependencies..."
if command -v pip3 &> /dev/null; then
    sudo -u "$ACTUAL_USER" pip3 install --user --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r "$(dirname "$0")/requirements.txt"
    echo "  Done"
else
    echo "  pip3 not found - install requirements.txt dependencies manually"
fi

echo
echo "All done! Remember to log out and back in."
