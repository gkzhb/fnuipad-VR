"""Suggested bindings for core OpenXR controller interaction profiles.

Keys are existing profile input names, not device-specific numeric button IDs.
Only paths defined by each interaction profile are suggested. System buttons
are deliberately absent: they belong to the runtime, not applications.
"""

BOOLEAN_INPUTS = (
    'trigger_click', 'trigger_touch', 'grip_click', 'grip_touch',
    'trackpad_click', 'trackpad_touch', 'thumbstick_click', 'thumbstick_touch',
    'menu', 'a_button', 'b_button', 'x_button', 'y_button', 'a_touch',
)
FLOAT_INPUTS = ('trigger', 'grip')
VECTOR_INPUTS = ('trackpad', 'thumbstick')


def profile_bindings():
    """Yield (profile path, hand, action name, component path)."""
    profiles = {}
    for profile in ('htc/vive_controller', 'oculus/touch_controller',
                    'valve/index_controller', 'khr/simple_controller',
                    'microsoft/motion_controller'):
        hands = {}
        for hand in ('left', 'right'):
            b = {'pose': 'input/grip/pose', 'haptic': 'output/haptic'}
            if profile == 'khr/simple_controller':
                b.update(trigger_click='input/select/click', menu='input/menu/click')
            else:
                b['trigger'] = 'input/trigger/value'
                if profile in ('htc/vive_controller', 'microsoft/motion_controller'):
                    b.update(grip_click='input/squeeze/click', menu='input/menu/click',
                             trackpad='input/trackpad', trackpad_click='input/trackpad/click',
                             trackpad_touch='input/trackpad/touch')
                if profile == 'htc/vive_controller':
                    b['trigger_click'] = 'input/trigger/click'
                if profile == 'microsoft/motion_controller':
                    b.update(thumbstick='input/thumbstick', thumbstick_click='input/thumbstick/click')
                if profile in ('oculus/touch_controller', 'valve/index_controller'):
                    b.update(grip='input/squeeze/value', trigger_touch='input/trigger/touch',
                             thumbstick='input/thumbstick', thumbstick_click='input/thumbstick/click',
                             thumbstick_touch='input/thumbstick/touch')
                    first, second = ('x', 'y') if hand == 'left' and profile == 'oculus/touch_controller' else ('a', 'b')
                    b[first + '_button'] = 'input/' + first + '/click'
                    b[second + '_button'] = 'input/' + second + '/click'
                    b['a_touch'] = 'input/' + first + '/touch'
                if profile == 'oculus/touch_controller' and hand == 'left':
                    b['menu'] = 'input/menu/click'
                if profile == 'valve/index_controller':
                    b.update(trigger_click='input/trigger/click', trackpad='input/trackpad',
                             trackpad_touch='input/trackpad/touch')
            hands[hand] = b
        profiles['/interaction_profiles/' + profile] = hands
    return profiles
