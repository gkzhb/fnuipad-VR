"""Background-only behavior without SteamVR/headset/uinput."""
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
from _openvr import OpenVRBackend, OpenVRError, SessionEnded


class FakeVR:
    VRApplication_Background = 3
    VREvent_Quit = 700
    TrackingUniverseSeated = 0
    k_unMaxTrackedDeviceCount = 4
    k_unTrackedDeviceIndexInvalid = 0xffffffff
    TrackedControllerRole_LeftHand = 1
    TrackedControllerRole_RightHand = 2
    k_EButton_SteamVR_Trigger = 33
    k_EButton_Grip = 2
    k_EButton_ApplicationMenu = 1
    k_EButton_A = 7
    k_EButton_Axis0 = 32
    Prop_Axis0Type_Int32 = 3002
    k_eControllerAxis_TrackPad = 1
    k_eControllerAxis_Joystick = 2
    k_eControllerAxis_Trigger = 3
    VREvent_t = NS

    def __init__(self):
        self.events = []
        self.roles = {1: 1, 2: 2}
        self.connected = self.valid = True
        self.pressed = (1 << 7) | (1 << 32)
        self.init = Mock(return_value=self)
        self.shutdown = Mock()
        self.acknowledgeQuit_Exiting = Mock()
        self.triggerHapticPulse = Mock()

    def pollNextEvent(self, event):
        if not self.events: return False
        event.eventType = self.events.pop(0)
        return True

    def getDeviceToAbsoluteTrackingPose(self, origin, seconds, count):
        assert origin == self.TrackingUniverseSeated and seconds == 0
        return [NS(bDeviceIsConnected=self.connected, bPoseIsValid=self.valid,
                   mDeviceToAbsoluteTracking=((1,0,0,1),(0,1,0,2),(0,0,1,3))) for _ in range(count)]

    def getTrackedDeviceIndexForControllerRole(self, role): return self.roles[role]

    def getControllerState(self, index):
        return True, NS(ulButtonPressed=self.pressed, ulButtonTouched=1 << 32,
                        rAxis=[NS(x=.3, y=.4), NS(x=.9, y=0), NS(x=0,y=0)])

    def getInt32TrackedDeviceProperty(self, index, prop):
        return [self.k_eControllerAxis_Joystick, self.k_eControllerAxis_Trigger, 0][prop-3002]


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.vr = FakeVR()
        self.backend = OpenVRBackend(self.vr)

    def tearDown(self): self.backend.close()

    def test_background_only_without_compositor(self):
        self.vr.init.assert_called_once_with(self.vr.VRApplication_Background)
        self.backend.update()  # Fake has no compositor, scene, or focus API.
        self.assertTrue(self.backend.controller('left').pose_valid)

    def test_named_controls_and_distinct_face_buttons(self):
        self.backend.update()
        left, right = self.backend.controller('left'), self.backend.controller('right')
        self.assertTrue(left.buttons['x_button'])
        self.assertNotIn('a_button', left.buttons)
        self.assertTrue(right.buttons['a_button'])
        self.assertFalse(right.buttons['b_button'])
        self.assertTrue(right.buttons['thumbstick_click'])
        self.assertNotIn('trackpad_x', right.axes)
        self.assertEqual(right.axes['thumbstick_y'], .4)
        self.assertTrue(right.buttons['trigger_click'])

    def test_disconnect_and_role_rediscovery_clear_stale_input(self):
        self.backend.update()
        self.vr.roles[1] = self.vr.k_unTrackedDeviceIndexInvalid
        self.vr.connected = False
        self.backend.update()
        for hand in ('left', 'right'):
            self.assertFalse(self.backend.controller(hand).buttons)
            self.assertFalse(self.backend.controller(hand).pose_valid)
        self.assertEqual(self.backend.ids, {})

    def test_tracking_loss_invalidates_pose(self):
        self.backend.update()
        self.vr.valid = False
        self.backend.update()
        self.assertFalse(self.backend.controller('left').pose_valid)

    def test_quit_acknowledged_and_shutdown_once(self):
        self.vr.events = [self.vr.VREvent_Quit]
        with self.assertRaises(SessionEnded): self.backend.update()
        self.vr.acknowledgeQuit_Exiting.assert_called_once()
        self.backend.close()
        self.vr.shutdown.assert_called_once()
        self.assertFalse(self.backend.controller('left').buttons)

    def test_runtime_error_clears_and_closes(self):
        self.backend.update()
        self.vr.getControllerState = Mock(side_effect=RuntimeError('lost runtime'))
        with self.assertRaises(OpenVRError): self.backend.update()
        self.assertFalse(self.backend.controller('left').buttons)
        self.vr.shutdown.assert_called_once()

    def test_haptic_duration_clamped(self):
        self.backend.update()
        self.backend.haptic('left', duration_ns=100_000_000)
        self.vr.triggerHapticPulse.assert_called_once_with(1, 0, 3999)

    def test_all_entrypoints_and_consumers_use_background_adapter(self):
        root = Path(__file__).resolve().parents[1]
        names = ['vr_gamepad_main.py', 'vr_wheel_main.py', 'vr_flightstick_main.py',
                 '_mapping_engine.py', '_vrgamepad.py', '_wheel.py', '_flightstick.py']
        for name in names:
            source = (root / name).read_text()
            self.assertNotIn('import _openxr', source)
            self.assertNotIn('from _openxr', source)
            self.assertIn('_openvr', source)


if __name__ == '__main__': unittest.main()
