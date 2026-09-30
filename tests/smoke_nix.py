"""Real OpenVR binding smoke test; does NOT connect to SteamVR or uinput."""
import ctypes
import importlib
import inspect
from pathlib import Path
import openvr

for name in ('evdev', 'tkinter'):
    module = importlib.import_module(name)
    path = Path(module.__file__).resolve()
    print(f'{name}: {path}')
    assert str(path).startswith('/nix/store/'), f'{name} shadows Nix dependency'

for library in ('libuuid.so.1', 'libvulkan.so.1', 'libGLX.so.0'):
    ctypes.CDLL(library)
    print(f'{library}: load OK')

assert openvr.VRApplication_Background != openvr.VRApplication_Scene
openvr.VREvent_t()
openvr.VRControllerState_t()
pose = openvr.TrackedDevicePose_t()
assert len(pose.mDeviceToAbsoluteTracking[0]) == 4
for name in ('pollNextEvent', 'acknowledgeQuit_Exiting', 'getControllerState',
             'getDeviceToAbsoluteTrackingPose', 'getTrackedDeviceIndexForControllerRole',
             'getInt32TrackedDeviceProperty', 'triggerHapticPulse'):
    print(name, inspect.signature(getattr(openvr.IVRSystem, name)))
print('OpenVR real-binding smoke passed; no runtime initialized')
