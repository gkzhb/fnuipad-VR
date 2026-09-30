"""OpenXR headless input session. No OpenVR dependency or graphics context.

The application owns one backend and calls update once per input tick. Action
spaces and inputs share one sync/time sample. Consumers never call XR directly.
"""
import ctypes
import logging
import time

from _vr_input import ControllerInput, pose_matrix
from _xr_bindings import BOOLEAN_INPUTS, FLOAT_INPUTS, VECTOR_INPUTS, profile_bindings

log = logging.getLogger(__name__)


class OpenXRError(RuntimeError):
    pass


class SessionEnded(OpenXRError):
    pass


class OpenXRBackend:
    def __init__(self, xr_module=None):
        self.instance = self.session = self.action_set = self.base_space = None
        self.spaces = {}
        self.actions = {}
        self.running = self.focused = False
        self.closed = False
        self._clear()
        try:
            if xr_module is None:
                import xr as xr_module
            self.xr = xr_module
            self._initialize()
        except Exception as exc:
            self.close()
            raise OpenXRError(f'OpenXR initialization failed: {exc}') from exc

    def _clear(self):
        self.states = {hand: ControllerInput() for hand in ('left', 'right')}

    def _initialize(self):
        xr = self.xr
        extensions = {p.extension_name.decode() if isinstance(p.extension_name, bytes)
                      else p.extension_name for p in xr.enumerate_instance_extension_properties()}
        if 'XR_MND_headless' not in extensions:
            raise OpenXRError('The active runtime does not support XR_MND_headless. '
                              'Select a runtime with headless input support via XR_RUNTIME_JSON. '
                              'A normal immersive session is not a background-input substitute.')
        time_extension = 'XR_KHR_convert_timespec_time'
        if time_extension not in extensions:
            raise OpenXRError(f'{time_extension} is required for frame-free headless pose sampling.')
        self.instance = xr.create_instance(xr.InstanceCreateInfo(
            application_info=xr.ApplicationInfo(application_name='fnuipad'),
            enabled_extension_names=['XR_MND_headless', time_extension]))
        # Resolve explicitly: pyopenxr 1.1.5301's convenience wrapper accesses
        # instance.instance, which is not a property of an Instance handle.
        self._convert_time = ctypes.cast(
            xr.get_instance_proc_addr(self.instance, 'xrConvertTimespecTimeToTimeKHR'),
            xr.PFN_xrConvertTimespecTimeToTimeKHR)
        system = xr.get_system(self.instance, xr.SystemGetInfo(form_factor=xr.FormFactor.HEAD_MOUNTED_DISPLAY))
        self.session = xr.create_session(self.instance, xr.SessionCreateInfo(system_id=system))
        self.hands = {hand: xr.string_to_path(self.instance, '/user/hand/' + hand)
                      for hand in ('left', 'right')}
        self.action_set = xr.create_action_set(self.instance, xr.ActionSetCreateInfo(
            action_set_name='gamepad', localized_action_set_name='Gamepad'))
        types = {**{n: xr.ActionType.BOOLEAN_INPUT for n in BOOLEAN_INPUTS},
                 **{n: xr.ActionType.FLOAT_INPUT for n in FLOAT_INPUTS},
                 **{n: xr.ActionType.VECTOR2F_INPUT for n in VECTOR_INPUTS},
                 'pose': xr.ActionType.POSE_INPUT, 'haptic': xr.ActionType.VIBRATION_OUTPUT}
        for name, kind in types.items():
            self.actions[name] = xr.create_action(self.action_set, xr.ActionCreateInfo(
                action_name=name, localized_action_name=name.replace('_', ' ').title(),
                action_type=kind, subaction_paths=list(self.hands.values())))
        for profile, hands in profile_bindings().items():
            bindings = [xr.ActionSuggestedBinding(
                action=self.actions[name], binding=xr.string_to_path(
                    self.instance, '/user/hand/' + hand + '/' + component))
                for hand, entries in hands.items() for name, component in entries.items()]
            try:
                xr.suggest_interaction_profile_bindings(self.instance, xr.InteractionProfileSuggestedBinding(
                    interaction_profile=xr.string_to_path(self.instance, profile), suggested_bindings=bindings))
            except xr.PathUnsupportedError:
                log.warning('Runtime does not support interaction profile %s', profile)
        xr.attach_session_action_sets(self.session, xr.SessionActionSetsAttachInfo(action_sets=[self.action_set]))
        identity = xr.Posef(orientation=xr.Quaternionf(0, 0, 0, 1))
        self.base_space = xr.create_reference_space(self.session, xr.ReferenceSpaceCreateInfo(
            reference_space_type=xr.ReferenceSpaceType.LOCAL, pose_in_reference_space=identity))
        for hand, path in self.hands.items():
            self.spaces[hand] = xr.create_action_space(self.session, xr.ActionSpaceCreateInfo(
                action=self.actions['pose'], subaction_path=path, pose_in_action_space=identity))

    def _events(self):
        xr = self.xr
        while True:
            try:
                event = xr.poll_event(self.instance)
            except xr.EventUnavailable:
                return
            if event.type == xr.StructureType.EVENT_DATA_INSTANCE_LOSS_PENDING:
                raise SessionEnded('OpenXR instance loss pending; restart the mapper.')
            if event.type != xr.StructureType.EVENT_DATA_SESSION_STATE_CHANGED:
                continue
            event = ctypes.cast(ctypes.byref(event), ctypes.POINTER(xr.EventDataSessionStateChanged)).contents
            state = event.state
            self.focused = state == xr.SessionState.FOCUSED
            if state == xr.SessionState.READY and not self.running:
                xr.begin_session(self.session, xr.SessionBeginInfo(
                    primary_view_configuration_type=xr.ViewConfigurationType.PRIMARY_STEREO))
                self.running = True
            elif state == xr.SessionState.STOPPING:
                if self.running:
                    xr.end_session(self.session)
                self.running = False
            elif state in (xr.SessionState.EXITING, xr.SessionState.LOSS_PENDING):
                raise SessionEnded('OpenXR session ended; restart the mapper.')

    def _state(self, hand, name, kind):
        xr = self.xr
        return getattr(xr, 'get_action_state_' + kind)(self.session, xr.ActionStateGetInfo(
            action=self.actions[name], subaction_path=self.hands[hand]))

    def _sample_time(self):
        xr = self.xr
        ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        timestamp = xr.timespec(ns // 1_000_000_000, ns % 1_000_000_000)
        result_time = xr.Time()
        result = xr.check_result(self._convert_time(
            self.instance, ctypes.byref(timestamp), ctypes.byref(result_time)))
        if result.is_exception():
            raise result
        return result_time.value

    def update(self):
        # Always replace snapshots, including on errors and lost focus.
        self._clear()
        if self.closed:
            raise SessionEnded('OpenXR backend is closed')
        xr = self.xr
        try:
            self._events()
            if not self.running or not self.focused:
                return
            # Headless needs no frame loop. Never block event polling on the
            # compositor: SteamVR can abort clients that miss its quit deadline.
            sample_time = self._sample_time()
            xr.sync_actions(self.session, xr.ActionsSyncInfo(active_action_sets=[
                xr.ActiveActionSet(action_set=self.action_set)]))
            states = {}
            for hand in self.hands:
                sample = ControllerInput()
                for name in BOOLEAN_INPUTS:
                    value = self._state(hand, name, 'boolean')
                    if value.is_active:
                        sample.buttons[name] = bool(value.current_state)
                for name in FLOAT_INPUTS:
                    value = self._state(hand, name, 'float')
                    if value.is_active:
                        sample.axes[name] = float(value.current_state)
                for name in VECTOR_INPUTS:
                    value = self._state(hand, name, 'vector2f')
                    if value.is_active:
                        sample.axes[name + '_x'] = value.current_state.x
                        sample.axes[name + '_y'] = value.current_state.y
                for name in FLOAT_INPUTS:
                    sample.buttons.setdefault(name + '_click', sample.axes.get(name, 0.0) >= 0.8)
                    if sample.buttons[name + '_click']:
                        sample.axes.setdefault(name, 1.0)
                pose = self._state(hand, 'pose', 'pose')
                if pose.is_active:
                    location = xr.locate_space(self.spaces[hand], self.base_space, sample_time)
                    valid = xr.SpaceLocationFlags.POSITION_VALID_BIT | xr.SpaceLocationFlags.ORIENTATION_VALID_BIT
                    if location.location_flags & valid == valid:
                        sample.matrix = pose_matrix(location.pose)
                states[hand] = sample
            self.states = states
        except SessionEnded:
            raise
        except xr.SessionNotFocused:
            self._clear()
            self.focused = False
        except Exception as exc:
            self._clear()
            raise OpenXRError(f'OpenXR input update failed: {exc}') from exc

    def controller(self, hand):
        return self.states[hand]

    def haptic(self, hand, amplitude=0.5, duration_ns=1_000_000):
        if not self.running or not self.focused or self.closed:
            return
        xr = self.xr
        try:
            xr.apply_haptic_feedback(self.session, xr.HapticActionInfo(
                action=self.actions['haptic'], subaction_path=self.hands[hand]),
                xr.HapticVibration(amplitude=max(0.0, min(1.0, amplitude)),
                                   duration=max(1, int(duration_ns)), frequency=0.0))
        except Exception as exc:
            raise OpenXRError(f'OpenXR haptic failed: {exc}') from exc

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._clear()
        if not hasattr(self, 'xr'):
            return
        # Destroy every successfully allocated resource, even after partial init.
        resources = [('space', s) for s in self.spaces.values()]
        resources += [('space', self.base_space), ('session', self.session),
                      ('action_set', self.action_set), ('instance', self.instance)]
        for kind, handle in resources:
            if handle is not None:
                try:
                    getattr(self.xr, 'destroy_' + kind)(handle)
                except Exception:
                    log.exception('Failed to destroy OpenXR %s', kind)
        self.running = self.focused = False


_backend = None


def init():
    global _backend
    if _backend is None:
        _backend = OpenXRBackend()
    return _backend


def get_backend():
    if _backend is None:
        raise OpenXRError('Initialize the OpenXR backend before creating a mapper.')
    return _backend


def shutdown():
    global _backend
    if _backend is not None:
        _backend.close()
        _backend = None
