"""SteamVR input-only adapter. Never creates a scene or compositor session.

Legacy controller state is runtime/driver dependent; foreground-game input
availability must be verified on hardware. No focus capture is attempted.
"""
from _vr_input import ControllerInput


class OpenVRError(RuntimeError):
    pass


class SessionEnded(OpenVRError):
    pass


class OpenVRBackend:
    def __init__(self, vr_module=None):
        self.closed = False
        self.initialized = False
        self.ids = {}
        self._clear()
        try:
            if vr_module is None:
                import openvr as vr_module
            self.vr = vr_module
            self.system = self.vr.init(self.vr.VRApplication_Background)
            self.initialized = True
        except Exception as exc:
            self.close()
            raise OpenVRError(f'OpenVR Background initialization failed: {exc}') from exc

    def _clear(self):
        self.states = {hand: ControllerInput() for hand in ('left', 'right')}

    def _events(self):
        vr = self.vr
        event = vr.VREvent_t()
        while self.system.pollNextEvent(event):
            if event.eventType == vr.VREvent_Quit:
                # Acknowledge before releasing the client. Never ignore the
                # runtime's deadline or ask it to terminate another application.
                self.system.acknowledgeQuit_Exiting()
                raise SessionEnded('SteamVR requested shutdown')

    def _read(self, hand, index, pose):
        vr = self.vr
        sample = ControllerInput()
        if not pose.bDeviceIsConnected:
            return sample
        if pose.bPoseIsValid:
            sample.matrix = tuple(tuple(float(pose.mDeviceToAbsoluteTracking[r][c])
                                        for c in range(4)) for r in range(3))
        valid, state = self.system.getControllerState(index)
        if not valid:
            return sample
        pressed, touched = state.ulButtonPressed, state.ulButtonTouched
        bits = {'trigger': vr.k_EButton_SteamVR_Trigger,
                'grip': vr.k_EButton_Grip}
        for name, bit in bits.items():
            sample.buttons[name + '_click'] = bool(pressed & (1 << bit))
            sample.buttons[name + '_touch'] = bool(touched & (1 << bit))
        sample.buttons['menu'] = bool(pressed & (1 << vr.k_EButton_ApplicationMenu))
        # Legacy Touch convention: A/X = A bit, B/Y = ApplicationMenu bit.
        # Other drivers may expose different emulation; do not alias A and B.
        primary, secondary = ('x_button', 'y_button') if hand == 'left' else ('a_button', 'b_button')
        sample.buttons[primary] = bool(pressed & (1 << vr.k_EButton_A))
        sample.buttons[secondary] = sample.buttons['menu']
        for axis_index, axis in enumerate(state.rAxis):
            kind = self.system.getInt32TrackedDeviceProperty(
                index, vr.Prop_Axis0Type_Int32 + axis_index)
            if kind in (vr.k_eControllerAxis_TrackPad, vr.k_eControllerAxis_Joystick):
                name = 'trackpad' if kind == vr.k_eControllerAxis_TrackPad else 'thumbstick'
                sample.axes[name + '_x'] = float(axis.x)
                sample.axes[name + '_y'] = float(axis.y)
                bit = vr.k_EButton_Axis0 + axis_index
                sample.buttons[name + '_click'] = bool(pressed & (1 << bit))
                sample.buttons[name + '_touch'] = bool(touched & (1 << bit))
            elif kind == vr.k_eControllerAxis_Trigger:
                # Standard legacy trigger is axis 1; axis 2 may be analog grip.
                if axis_index in (1, 2):
                    sample.axes['trigger' if axis_index == 1 else 'grip'] = float(axis.x)
        for name in ('trigger', 'grip'):
            sample.axes.setdefault(name, float(sample.buttons[name + '_click']))
            sample.buttons[name + '_click'] |= sample.axes[name] >= 0.8
        return sample

    def update(self):
        self._clear()
        self.ids = {}
        if self.closed:
            raise SessionEnded('OpenVR backend is closed')
        try:
            self._events()
            vr = self.vr
            # System poses do not wait for compositor frames or acquire focus.
            poses = self.system.getDeviceToAbsoluteTrackingPose(
                vr.TrackingUniverseSeated, 0.0, vr.k_unMaxTrackedDeviceCount)
            states, ids = {}, {}
            for hand, role in (('left', vr.TrackedControllerRole_LeftHand),
                               ('right', vr.TrackedControllerRole_RightHand)):
                index = self.system.getTrackedDeviceIndexForControllerRole(role)
                if index == vr.k_unTrackedDeviceIndexInvalid:
                    states[hand] = ControllerInput()
                    continue
                states[hand] = self._read(hand, index, poses[index])
                if poses[index].bDeviceIsConnected:
                    ids[hand] = index
            self.states, self.ids = states, ids
        except SessionEnded:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise OpenVRError(f'OpenVR input update failed: {exc}') from exc

    def controller(self, hand):
        return self.states[hand]

    def haptic(self, hand, amplitude=0.5, duration_ns=1_000_000):
        if self.closed or hand not in self.ids or amplitude <= 0:
            return
        try:
            self.system.triggerHapticPulse(self.ids[hand], 0,
                max(1, min(3999, int(duration_ns / 1000))))
        except Exception as exc:
            raise OpenVRError(f'OpenVR haptic failed: {exc}') from exc

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._clear()
        self.ids = {}
        if self.initialized:
            self.initialized = False
            self.vr.shutdown()


_backend = None


def init():
    global _backend
    if _backend is None:
        _backend = OpenVRBackend()
    return _backend


def get_backend():
    if _backend is None:
        raise OpenVRError('Initialize OpenVR Background before creating a mapper')
    return _backend


def shutdown():
    global _backend
    backend, _backend = _backend, None
    if backend is not None:
        backend.close()
