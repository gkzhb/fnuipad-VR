"""No headset, loader, uinput, or third-party packages needed."""
import ctypes
import sys
import unittest
from types import SimpleNamespace as NS, ModuleType
from unittest.mock import Mock, patch

from _openxr import OpenXRBackend, OpenXRError, SessionEnded
from _vr_input import ControllerInput, pose_matrix
from _xr_bindings import profile_bindings


class FakeGamepad:
    def __init__(self, **kwargs):
        self.buttons, self.sticks, self.triggers = {}, {}, {}
    def set_button(self, name, value): self.buttons[name] = value
    def set_stick(self, name, x, y): self.sticks[name] = (x, y)
    def set_trigger(self, name, value): self.triggers[name] = value
    def set_dpad(self, x, y): self.dpad = (x, y)
    def sync(self): pass
    def close(self): pass


class Event(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('state', ctypes.c_int)]


class Unavailable(Exception): pass


class NotFocused(Exception): pass


class FakeXR:
    SessionNotFocused = NotFocused
    SessionState = NS(READY=1, FOCUSED=2, STOPPING=3, EXITING=4, LOSS_PENDING=5)
    StructureType = NS(EVENT_DATA_SESSION_STATE_CHANGED=1, EVENT_DATA_INSTANCE_LOSS_PENDING=2)
    EventDataSessionStateChanged = Event
    EventUnavailable = Unavailable
    PathUnsupportedError = Unavailable
    SpaceLocationFlags = NS(POSITION_VALID_BIT=1, ORIENTATION_VALID_BIT=2)
    ViewConfigurationType = NS(PRIMARY_STEREO=1)
    EnvironmentBlendMode = NS(OPAQUE=1)
    ActionType = NS(BOOLEAN_INPUT=1, FLOAT_INPUT=2, VECTOR2F_INPUT=3, POSE_INPUT=4, VIBRATION_OUTPUT=5)
    FormFactor = NS(HEAD_MOUNTED_DISPLAY=1)
    ReferenceSpaceType = NS(LOCAL=1)

    class timespec(ctypes.Structure):
        _fields_ = [('tv_sec', ctypes.c_long), ('tv_nsec', ctypes.c_long)]
    Time = ctypes.c_int64
    PFN_xrConvertTimespecTimeToTimeKHR = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int64))

    @staticmethod
    def check_result(result):
        return NS(is_exception=lambda: False)

    def get_instance_proc_addr(self, instance, name):
        def convert(instance, timestamp, output):
            output[0] = 123456
            return 0
        self.convert_callback = self.PFN_xrConvertTimespecTimeToTimeKHR(convert)
        return self.convert_callback

    def __init__(self):
        self.events = []
        self.values = {}
        self.calls = []
        self.location_flags = 3
        self.extensions = [NS(extension_name=b'XR_MND_headless'),
                           NS(extension_name=b'XR_KHR_convert_timespec_time')]
        self.fail_create_space = False

    def __getattr__(self, name):
        if name[0].isupper():
            return lambda *args, **kw: NS(**kw)
        if name.startswith('get_action_state_'):
            kind = name.removeprefix('get_action_state_')
            def state(session, info):
                value = self.values.get((info.subaction_path, info.action))
                return NS(is_active=value is not None, current_state=value)
            return state
        def call(*args, **kwargs):
            self.calls.append((name, args))
            if name == 'create_instance': return 1
            if name.startswith('create_'): return name
        return call

    def enumerate_instance_extension_properties(self): return self.extensions
    def create_action(self, action_set, info): return info.action_name
    def string_to_path(self, instance, path): return path
    def create_action_space(self, session, info):
        if self.fail_create_space: raise RuntimeError('space failed')
        return info.subaction_path
    def poll_event(self, instance):
        if not self.events: raise Unavailable()
        return self.events.pop(0)
    def wait_frame(self, session): return NS(predicted_display_time=123456)
    def locate_space(self, *args):
        self.calls.append(('locate_space', args))
        return NS(location_flags=self.location_flags, pose=NS(
            orientation=NS(x=0, y=0, z=0, w=1), position=NS(x=1, y=2, z=3)))


class BackendTests(unittest.TestCase):
    def make_backend(self):
        xr = FakeXR()
        backend = OpenXRBackend(xr)
        xr.events = [Event(1, 1), Event(1, 2)]
        return backend, xr

    def test_missing_extension(self):
        xr = FakeXR()
        xr.extensions = []
        with self.assertRaisesRegex(OpenXRError, 'XR_MND_headless'):
            OpenXRBackend(xr)
        self.assertFalse(any(n == 'create_session' for n, _ in xr.calls))

    def test_partial_initialization_cleanup(self):
        xr = FakeXR()
        xr.fail_create_space = True
        with self.assertRaisesRegex(OpenXRError, 'space failed'): OpenXRBackend(xr)
        self.assertEqual([n for n, _ in xr.calls if n.startswith('destroy_')],
                         ['destroy_space', 'destroy_session', 'destroy_action_set', 'destroy_instance'])

    def test_actions_pose_time_and_focus_loss(self):
        backend, xr = self.make_backend()
        hand = '/user/hand/right'
        xr.values[(hand, 'trigger')] = 0.9
        xr.values[(hand, 'a_button')] = True
        xr.values[(hand, 'b_button')] = False
        xr.values[(hand, 'thumbstick')] = NS(x=0.2, y=-0.4)
        xr.values[(hand, 'pose')] = True
        backend.update()
        right = backend.controller('right')
        self.assertTrue(right.buttons['trigger_click'])
        self.assertTrue(right.buttons['a_button'])
        self.assertFalse(right.buttons['b_button'])
        self.assertNotIn('trackpad_x', right.axes)
        self.assertEqual(right.matrix[0][3], 1)
        self.assertEqual(next(args[-1] for n, args in xr.calls if n == 'locate_space'), 123456)
        xr.events = [Event(1, 0)]
        backend.update()
        self.assertEqual(backend.controller('right'), ControllerInput())

    def test_invalid_pose_and_disconnect(self):
        backend, xr = self.make_backend()
        xr.values[('/user/hand/left', 'pose')] = True
        xr.location_flags = 1
        backend.update()
        self.assertFalse(backend.controller('left').pose_valid)
        xr.values.clear()
        backend.update()
        self.assertFalse(any(backend.controller('left').buttons.values()))

    def test_stop_restart_exit(self):
        backend, xr = self.make_backend()
        backend.update()
        xr.events = [Event(1, 3)]
        backend.update()
        self.assertFalse(backend.running)
        xr.events = [Event(1, 1), Event(1, 2)]
        backend.update()
        self.assertTrue(backend.running)
        xr.events = [Event(1, 4)]
        with self.assertRaises(SessionEnded): backend.update()
        backend.close()
        count = len(xr.calls)
        backend.close()
        self.assertEqual(count, len(xr.calls))

    def test_headless_never_waits_for_compositor(self):
        backend, xr = self.make_backend()
        xr.wait_frame = Mock(side_effect=AssertionError('must not wait for a frame'))
        backend.update()
        xr.wait_frame.assert_not_called()
        xr.events = [Event(1, 4)]
        with self.assertRaises(SessionEnded): backend.update()

    def test_sync_error_clears_inputs(self):
        backend, xr = self.make_backend()
        xr.sync_actions = Mock(side_effect=RuntimeError('sync failed'))
        with self.assertRaisesRegex(OpenXRError, 'sync failed'): backend.update()
        self.assertFalse(any(n in ('begin_frame', 'end_frame') for n, _ in xr.calls))
        self.assertEqual(backend.controller('right'), ControllerInput())

    def test_haptic_units_and_clamp(self):
        backend, xr = self.make_backend()
        backend.update()
        backend.haptic('left', amplitude=2, duration_ns=2500000)
        args = next(args for n, args in xr.calls if n == 'apply_haptic_feedback')
        self.assertEqual(args[2].duration, 2500000)
        self.assertEqual(args[2].amplitude, 1)

    def test_binding_paths(self):
        profiles = profile_bindings()
        touch = profiles['/interaction_profiles/oculus/touch_controller']
        self.assertEqual(touch['left']['x_button'], 'input/x/click')
        self.assertEqual(touch['right']['b_button'], 'input/b/click')
        self.assertNotIn('menu', touch['right'])
        for hands in profiles.values():
            for bindings in hands.values(): self.assertNotIn('system', bindings)

    def test_quaternion(self):
        matrix = pose_matrix(NS(orientation=NS(x=0, y=1, z=0, w=0), position=NS(x=1, y=2, z=3)))
        self.assertEqual(matrix, ((-1, 0, 0, 1), (0, 1, 0, 2), (0, 0, -1, 3)))


class ConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake = ModuleType('_linuxgamepad')
        fake.LinuxGamepad = FakeGamepad
        cls.modules = patch.dict(sys.modules, {'_linuxgamepad': fake})
        cls.modules.start()

    @classmethod
    def tearDownClass(cls): cls.modules.stop()

    def test_mapping_releases_inactive_inputs(self):
        from _mapping_engine import MappingEngine
        from _mapping import create_default_profile
        backend = NS(update=Mock(), controller=lambda hand: states[hand])
        states = {'left': ControllerInput(), 'right': ControllerInput(
            buttons={'a_button': True, 'b_button': False}, axes={'trigger': 0.9})}
        with patch('_mapping_engine.get_backend', return_value=backend):
            engine = MappingEngine(create_default_profile())
        engine.update()
        self.assertTrue(engine.gamepad.buttons['a'])
        self.assertFalse(engine.gamepad.buttons['b'])
        states['right'] = ControllerInput()
        engine.update()
        self.assertFalse(engine.gamepad.buttons['a'])
        self.assertEqual(engine.gamepad.triggers['right'], 0)
        self.assertEqual(backend.update.call_count, 2)

    def test_wheel_and_flightstick_tracking_loss_and_edit(self):
        from _wheel import Wheel, WheelConfig
        from _flightstick import FlightStick, FlightStickConfig
        valid = ControllerInput(buttons={'trigger_click': True},
                                matrix=((1, 0, 0, 0.2), (0, 1, 0, 0.3), (0, 0, 1, -0.4)))
        states = {'left': valid, 'right': valid}
        backend = NS(update=Mock(), controller=lambda hand: states[hand])
        with patch('_wheel.get_backend', return_value=backend):
            wheel = Wheel(WheelConfig(wheel_show_wheel=False), FakeGamepad())
        with patch('_flightstick.get_backend', return_value=backend):
            stick = FlightStick(FlightStickConfig(show_stick=False, show_throttle=False), FakeGamepad())
        wheel.edit_mode()
        stick.edit_mode()
        self.assertEqual(wheel.config.wheel_center, (0.2, 0.3, -0.4))
        self.assertEqual(stick.config.stick_anchor, (0.2, 0.3, -0.4))
        states['right'] = ControllerInput()
        wheel._left_controller_grabbed = True
        stick._stick_grabbed = True
        stick._pitch = 0.7
        wheel.update()
        stick.update()
        self.assertFalse(wheel._left_controller_grabbed)
        self.assertEqual(wheel.gamepad.sticks['left'], (0.0, 0.0))
        self.assertFalse(stick._stick_grabbed)
        self.assertEqual(stick.gamepad.sticks['right'], (0.0, 0.0))
        self.assertEqual(backend.update.call_count, 4)

    def test_wheel_angle_wrap(self):
        from _wheel import Wheel, WheelConfig
        from math import pi
        with patch('_wheel.get_backend', return_value=NS()):
            wheel = Wheel(WheelConfig(wheel_show_wheel=False), FakeGamepad())
        wheel._wheel_angles.clear()
        wheel._wheel_angles.extend([pi - 0.1, -pi + 0.1])
        wheel.unwrap_wheel_angles()
        self.assertAlmostEqual(wheel._wheel_angles[-1], pi + 0.1)

    def test_legacy_gamepad_uses_thumbstick(self):
        from _vrgamepad import VRGamepad
        state = ControllerInput(buttons={'thumbstick_touch': True}, axes={'thumbstick_x': 0.8, 'thumbstick_y': 0.0})
        backend = NS(update=Mock(), controller=lambda hand: state)
        with patch('_vrgamepad.get_backend', return_value=backend): gamepad = VRGamepad()
        gamepad.update()
        self.assertGreater(gamepad.gamepad.sticks['left'][0], 0)


if __name__ == '__main__': unittest.main()
