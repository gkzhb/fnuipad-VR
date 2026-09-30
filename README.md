# VR Gamepad Mapper

A Linux tool that maps VR controller inputs to a virtual gamepad using OpenVR Background and uinput.

**SteamVR coexistence:** all launchers connect as `VRApplication_Background`.
They never create an OpenXR session, acquire a scene, capture input focus or wait
for compositor frames. The previous OpenXR headless implementation was observed
to become `OpenXRScene` on SteamVR and cause games to be terminated; it remains
as unselected legacy code only. Do not run it alongside a game.

**Limitations:** background legacy controller input depends on SteamVR and the
controller driver. Both launch orders and input with the game focused still need
hardware acceptance. Old wheel/hand/stick/throttle overlays remain disabled;
display flags are accepted but have no visual effect. Physics and calibration
remain available. Existing mapping profiles and uinput output are preserved.

## Features

- **Virtual Gamepad**: Creates a 32-button, 8-axis virtual joystick device
- **Flexible Mapping**: Configure any VR input to any gamepad output
- **Chord Support**: Combine buttons (e.g., Grip+Trigger = Guide)
- **Profile System**: Save and load mapping configurations
- **GUI Tools**: Visual configuration editor and gamepad monitor
- **Wine/Proton Compatible**: Full button support in Windows games

## Requirements

- Linux with uinput support
- Python 3.10+
- SteamVR running with paired controllers
- Python packages from `requirements.txt` (`openvr==1.26.701`)
- Runtime/controller pairing must already be configured

## Installation

### NixOS / Nix dev shell (recommended)

The flake provides Python 3.12, pip, Nix-built `evdev`, Tk (GUI), NumPy,
GLFW, PyOpenGL, the OpenXR loader and GLX/EGL dispatch libraries (`libglvnd`).
`openvr` is installed with `--no-deps` into the project `.venv` via
**Tsinghua PyPI**, not into the system Python. Its transitive dependencies come
from Nix, avoiding incompatible manylinux wheels. Entering the shell does not run
pip automatically.

```bash
nix develop
setup-python
source .venv/bin/activate
python tests/smoke_nix.py
python -m pip check
python -m unittest discover -s tests -v
python vr_gamepad_main.py
```

If `flake.nix` is still untracked in a Git checkout, use `nix develop path:.`
(Nix's default Git source excludes untracked files). Re-enter the shell and activate
the venv for later sessions. `setup-python` records the Nix Python environment
path; when it changes (or an old unmarked venv exists), it preserves `.venv` as
`.venv.backup.<timestamp>.<pid>` and creates a fresh environment. Backups are not
deleted automatically. Activate the new venv again after running the helper.
Do not install transitive dependencies into this venv with `pip -r requirements.txt`;
use `setup-python`. `tests/smoke_nix.py` verifies that dependencies load from
`/nix/store`, loads native libraries and checks real binding structures without a headset.
The helper pins `openvr==1.26.701` and `setuptools==80.9.0` (OpenVR requires
`pkg_resources`, removed in setuptools 81+); this is a development venv, not a fully
Nix-locked Python package closure. `flake.lock` pins nixpkgs.

The nixpkgs source uses the Tsinghua `nix-channels` mirror. This is distinct from
PyPI: Nix binary substitutes still use your configured Nix caches. The project
does not modify system-wide caches or trust settings. If cache downloads are slow,
configure a trusted Nix mirror in your NixOS configuration separately.

Start SteamVR separately. `XR_RUNTIME_JSON` does not select the default OpenVR
backend. The shell retains native graphics/loader dependencies for compatibility;
it does not install or start SteamVR.

On NixOS, configure uinput declaratively rather than running `setup-script.sh`:

```nix
# In configuration.nix; replace YOUR_USER with your login name.
boot.kernelModules = [ "uinput" ];
users.users.YOUR_USER.extraGroups = [ "input" ];
services.udev.extraRules = ''
  KERNEL=="uinput", GROUP="input", MODE="0660"
  SUBSYSTEM=="input", ATTRS{name}=="VR Gamepad*", ENV{ID_INPUT_JOYSTICK}="1"
  SUBSYSTEM=="input", ATTRS{name}=="Test Gamepad*", ENV{ID_INPUT_JOYSTICK}="1"
'';
```

Apply with your normal `nixos-rebuild` workflow and log out/back in. Membership in
`input` grants access to input devices; only grant it to trusted local users.

### Other Linux distributions: install dependencies

```bash
python -m pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

### Other Linux distributions: setup permissions

Run the setup script (requires sudo):

```bash
sudo ./setup-script.sh
```

Or manually:

```bash
sudo modprobe uinput
sudo usermod -aG input $USER
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
```

Log out and back in for group changes to take effect.

## Usage

### Launcher

```bash
./start.sh                              # Default gamepad mapper
./start.sh gamepad -c default-profile.json
./start.sh wheel --degrees 540 --no-wheel
./start.sh flightstick --edit
./start.sh gamepad --help
```

The launcher enters the locked Nix dev shell, runs the idempotent `setup-python`
helper, and starts the selected application. It works from any directory and
preserves application arguments and exit status. Relative
profile paths resolve from the project directory; use absolute paths for external
profiles. First launch requires network access for uncached dependencies.

### SteamVR background setup and acceptance

Start SteamVR and pair/wake the controllers, then use `./start.sh` (gamepad),
`./start.sh wheel --no-wheel`, or `./start.sh flightstick --edit`.

Input uses legacy OpenVR controller state. Axis-type properties distinguish
trackpads from thumbsticks. For Touch-style legacy emulation, A/X use the A bit
and B/Y use ApplicationMenu; other driver mappings may differ. System buttons
are not exposed. JSON input names are unchanged; validate bindings on your device.

Poses use OpenVR seated space (meters, +Y up, -Z forward). Recalibrate anchors
with `--edit` after switching from OpenXR LOCAL space. Tracking loss clears pose
validity; disconnect clears input. Quit events are acknowledged and the mapper
closes its virtual device.

Hardware acceptance (not established by unit tests):
1. Test game-first and mapper-first launch orders, after stopping any OLD mapper.
2. Verify `vrserver.txt` classifies the mapper as Background, not OpenXRScene,
   with no scene transition or Quit/Kill directed at the other application.
3. With ETS2 focused, verify controller axes/buttons and wheel calibration.
4. Stop the mapper and disconnect controllers; confirm no stuck input or game exit.

### Run with default mappings

```bash
python vr_gamepad_main.py
```

### Run with a custom profile

```bash
python vr_gamepad_main.py -c my_profile.json
```

### Open the configuration GUI

```bash
python vr_gamepad_main.py --gui
```

### Open the gamepad monitor

```bash
python vr_gamepad_main.py --monitor
```

### List available inputs/outputs

```bash
python vr_gamepad_main.py --list-inputs
python vr_gamepad_main.py --list-outputs
```

### Save default profile to file

```bash
python vr_gamepad_main.py --save-default my_profile.json
```

## Default Mapping (Quest/Index Controllers)

| VR Input | Gamepad Output |
|----------|----------------|
| Left Thumbstick | Left Stick |
| Right Thumbstick | Right Stick |
| Left Trigger | Left Trigger (LT) |
| Right Trigger | Right Trigger (RT) |
| Left Grip | Left Bumper (LB) |
| Right Grip | Right Bumper (RB) |
| A Button | A |
| B Button | B |
| X Button | X |
| Y Button | Y |
| Left Thumbstick Click | L3 |
| Right Thumbstick Click | R3 |
| Left Menu | Select |
| Right Menu | Start |
| Right Grip + Right Trigger | Guide |

## Creating Custom Mappings

### Using the GUI

1. Run `python vr_gamepad_main.py --gui`
2. Click "Add Mapping"
3. Select input controller (left/right), type (button/axis), and input name
4. Select output type and name
5. Optionally add conditions for chords
6. Save profile to JSON file

### Profile JSON Format

```json
{
  "name": "My Profile",
  "mappings": [
    {
      "name": "A Button",
      "input": { "type": "button", "controller": "right", "name": "a_button" },
      "output": { "type": "button", "name": "a" },
      "conditions": [],
      "modifiers": { "invert": false, "sensitivity": 1.0, "deadzone": 0.0 },
      "priority": 0,
      "enabled": true
    }
  ],
  "settings": {
    "global_deadzone": 0.1,
    "haptic_intensity": 0.5
  }
}
```

### Chord Example

Map Grip+Trigger to Guide button:

```json
{
  "name": "Guide (Chord)",
  "input": { "type": "button", "controller": "right", "name": "trigger_click" },
  "output": { "type": "button", "name": "guide" },
  "conditions": [
    { "type": "button_held", "controller": "right", "input": "grip_click", "value": 0.5 }
  ],
  "priority": 10
}
```

Higher priority mappings are checked first, so chords take precedence over regular mappings.

## VR Inputs

**Buttons** (left/right controller):
- `trigger_click`, `trigger_touch`
- `grip_click`, `grip_touch`
- `trackpad_click`, `trackpad_touch`
- `thumbstick_click`, `thumbstick_touch`
- `menu`, `system`
- `a_button`, `b_button` (right) / `x_button`, `y_button` (left)

**Axes** (left/right controller):
- `trigger`, `grip`
- `trackpad_x`, `trackpad_y`
- `thumbstick_x`, `thumbstick_y`

## Gamepad Outputs

**Buttons**:
- Face: `a`, `b`, `x`, `y`
- Bumpers: `lb`, `rb`
- Sticks: `ls`, `rs`
- Menu: `start`, `select`, `guide`
- D-pad: `dpad_up`, `dpad_down`, `dpad_left`, `dpad_right`
- Directional clicks: `ls_up`, `ls_down`, `ls_left`, `ls_right`, `rs_up`, `rs_down`, `rs_left`, `rs_right`
- Back paddles: `back_lu`, `back_ll`, `back_ru`, `back_rl`
- Generic: `btn_1` through `btn_32`

**Axes**:
- Sticks: `left_stick_x`, `left_stick_y`, `right_stick_x`, `right_stick_y`
- Triggers: `left_trigger`, `right_trigger`
- D-pad: `dpad_x`, `dpad_y`
- Generic: `axis_1` through `axis_8`

## Wine/Proton Setup

By default, Wine uses SDL which limits detection to ~10 XInput buttons. To enable full 32-button support:

```bash
# Enable evdev mode (full button support)
python wine_setup.py evdev

# For Proton games, specify the prefix
python wine_setup.py --prefix ~/.steam/steam/steamapps/compatdata/<APPID>/pfx evdev

# Revert to SDL mode if needed
python wine_setup.py sdl

# Check current configuration
python wine_setup.py status
```

Test with Wine's joystick control panel:

```bash
wine control joy.cpl
```

## Testing

Hardware-independent regression tests (no loader/headset/uinput needed):

```bash
python -m unittest discover -s tests -v
```

These verify action snapshots, focus/session transitions, cleanup, pose conversion,
haptic units and mapping release. They do **not** establish hardware compatibility.
For hardware acceptance, test all three entry points, reconnect both controllers,
remove focus, calibrate anchors and verify input while the target game is running.

Test the virtual gamepad without VR:

```bash
# Automated test
python test_gamepad.py

# Interactive keyboard test
python test_gamepad.py --interactive
```

Test evdev and 32-button support (including Wine compatibility):

```bash
# Basic evdev test
python test_wine_evdev.py

# Verbose output
python test_wine_evdev.py -v

# Include Wine detection test
python test_wine_evdev.py --wine

# Include stress test
python test_wine_evdev.py --stress

# All tests
python test_wine_evdev.py -v --wine --stress
```

Verify with evtest:

```bash
evtest /dev/input/eventX  # where X is your device
```

## Troubleshooting

### Permission denied for /dev/uinput

```bash
sudo modprobe uinput
sudo usermod -aG input $USER
# Log out and back in
```

### OpenVR initialization fails

Start SteamVR and check headset/controller connection. Verify `setup-python`
completed and the OpenVR native library and SteamVR client can load.

### Controllers produce no input

Pair/wake controllers in SteamVR. Legacy state availability depends on the driver
and foreground application's input handling. Do not switch to Scene mode as a
workaround; that can terminate your game. Check foreground-game input on hardware.

### Game doesn't see all buttons

Run `python wine_setup.py evdev` to enable full button detection in Wine/Proton games.

## Files

| File | Description |
|------|-------------|
| `vr_gamepad_main.py` | Main entry point |
| `_linuxgamepad.py` | Virtual gamepad via uinput |
| `_mapping.py` | Mapping profile system |
| `_openvr.py` | Default Background-only input, poses, quit handling and haptics |
| `_openxr.py` | Unselected legacy backend; unsafe for SteamVR game coexistence |
| `_vr_input.py` | Runtime-independent controller snapshots |
| `_xr_bindings.py` | Controller interaction profile bindings |
| `_mapping_engine.py` | Input processing engine |
| `config_gui.py` | Configuration GUI |
| `monitor_gui.py` | Gamepad state monitor |
| `test_gamepad.py` | Testing utility |
| `test_wine_evdev.py` | evdev and Wine compatibility test |
| `wine_joy_test.c` | Windows joystick test source (for Wine) |
| `wine_joy_test.exe` | Compiled Windows test (auto-built if missing) |
| `setup-script.sh` | Permission setup script |
| `wine_setup.py` | Wine/Proton configuration |

## License

MIT
