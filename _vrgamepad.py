"""
VR Controller to Gamepad mapper using OpenVR Background and Linux evdev
Maps VR controller inputs to a virtual Xbox-style gamepad
"""

from _openvr import get_backend
from math import atan2, pi, sqrt
from dataclasses import dataclass, field
from typing import Optional, Dict, Set
from enum import Enum, auto

from _linuxgamepad import LinuxGamepad


class StickZone(Enum):
    """Directional zones for stick/trackpad"""
    CENTER = auto()
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()


@dataclass
class ControllerState:
    """Tracks state for one VR controller"""
    # Trackpad/thumbstick position (-1 to 1)
    stick_x: float = 0.0
    stick_y: float = 0.0
    
    # Trigger value (0 to 1)
    trigger: float = 0.0
    
    # Button states
    trigger_pressed: bool = False
    grip_pressed: bool = False
    trackpad_pressed: bool = False
    trackpad_touched: bool = False
    menu_pressed: bool = False
    system_pressed: bool = False
    
    # For tracking state changes
    prev_trackpad_pressed: bool = False
    prev_trigger_pressed: bool = False
    prev_grip_pressed: bool = False
    
    # Current stick zone when pressed
    stick_zone: StickZone = StickZone.CENTER


@dataclass 
class GamepadConfig:
    """Configuration for VR to gamepad mapping"""
    # Deadzone for analog sticks (0.0 to 1.0)
    stick_deadzone: float = 0.15
    
    # Threshold for directional stick clicks
    direction_threshold: float = 0.5
    
    # Trigger threshold to count as "pressed"
    trigger_press_threshold: float = 0.8
    
    # Whether to use trackpad touch for stick input (vs only when pressed)
    stick_on_touch: bool = True
    
    # Invert Y axis
    invert_y_left: bool = False
    invert_y_right: bool = False
    
    # Sensitivity multiplier
    stick_sensitivity: float = 1.0
    
    # Face button layout on right trackpad
    # Zones: up=Y, down=A, left=X, right=B
    face_button_zones: bool = True
    
    # D-pad on left trackpad when clicked
    dpad_on_left: bool = True
    
    # Map grips to bumpers vs back buttons
    grip_as_bumper: bool = True
    
    # Haptic feedback intensity (0.0 to 1.0)
    haptic_intensity: float = 0.5


class VRGamepad:
    """
    Maps VR controllers to a virtual gamepad.
    
    Default mapping (customizable via config):
    
    Left Controller:
        - Trackpad/Stick: Left analog stick
        - Trackpad click + direction: D-pad
        - Trackpad click center: L3
        - Trigger: Left trigger (LT)
        - Grip: Left bumper (LB) or back button
        - Menu: Select/Back
    
    Right Controller:
        - Trackpad/Stick: Right analog stick  
        - Trackpad click + direction: Face buttons (A/B/X/Y)
        - Trackpad click center: R3
        - Trigger: Right trigger (RT)
        - Grip: Right bumper (RB) or back button
        - Menu: Start
        - System: Guide
    """
    
    def __init__(self, config: Optional[GamepadConfig] = None):
        self.config = config or GamepadConfig()
        self.vrsys = get_backend()
        self.gamepad = LinuxGamepad()
        
        self.left = ControllerState()
        self.right = ControllerState()
        
        # Track which buttons are currently pressed (for edge detection)
        self._pressed_buttons: Set[str] = set()
        
        # Controller indices (will be set on first update)
        self._left_id: Optional[int] = None
        self._right_id: Optional[int] = None
    
    def _apply_deadzone(self, x: float, y: float) -> tuple[float, float]:
        """Apply radial deadzone to stick input"""
        magnitude = sqrt(x*x + y*y)
        if magnitude < self.config.stick_deadzone:
            return 0.0, 0.0
        
        # Rescale so edge of deadzone becomes 0
        scale = (magnitude - self.config.stick_deadzone) / (1.0 - self.config.stick_deadzone)
        scale = min(scale, 1.0)  # Clamp
        
        # Normalize and rescale
        if magnitude > 0:
            x = (x / magnitude) * scale * self.config.stick_sensitivity
            y = (y / magnitude) * scale * self.config.stick_sensitivity
        
        return max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y))
    
    def _get_zone(self, x: float, y: float) -> StickZone:
        """Determine which zone the stick is in"""
        threshold = self.config.direction_threshold
        
        if abs(x) < threshold and abs(y) < threshold:
            return StickZone.CENTER
        
        # Determine primary direction
        if abs(x) > abs(y):
            return StickZone.RIGHT if x > 0 else StickZone.LEFT
        else:
            return StickZone.UP if y > 0 else StickZone.DOWN
    
    def _read_controller(self, controller_id: int) -> ControllerState:
        """Read raw state from a VR controller"""
        state = ControllerState()
        
        snapshot = self.vrsys.controller(controller_id)
        buttons, axes = snapshot.buttons, snapshot.axes
        stick = 'thumbstick' if 'thumbstick_x' in axes else 'trackpad'
        state.stick_x = axes.get(stick + '_x', 0.0)
        state.stick_y = axes.get(stick + '_y', 0.0)
        state.trigger = axes.get('trigger', 0.0)
        state.trigger_pressed = buttons.get('trigger_click', False)
        state.grip_pressed = buttons.get('grip_click', False)
        state.trackpad_pressed = buttons.get(stick + '_click', False)
        state.trackpad_touched = buttons.get(stick + '_touch', False)
        state.menu_pressed = buttons.get('menu', False)
        state.system_pressed = False  # Reserved for the runtime.

        state.stick_zone = self._get_zone(state.stick_x, state.stick_y)
        
        return state
    
    def _button_edge(self, name: str, pressed: bool) -> tuple[bool, bool]:
        """
        Detect button press/release edges.
        Returns (just_pressed, just_released)
        """
        was_pressed = name in self._pressed_buttons
        
        if pressed and not was_pressed:
            self._pressed_buttons.add(name)
            return True, False
        elif not pressed and was_pressed:
            self._pressed_buttons.discard(name)
            return False, True
        
        return False, False
    
    def _trigger_haptic(self, controller_id: int, intensity: float = 1.0):
        """Trigger haptic feedback on controller"""
        if self.config.haptic_intensity > 0:
            duration = int(1000 * intensity * self.config.haptic_intensity)
            self.vrsys.haptic(controller_id, duration_ns=duration * 1000)
    
    def _process_left_controller(self, left_id: int):
        """Process left controller inputs"""
        prev = ControllerState(
            prev_trackpad_pressed=self.left.trackpad_pressed,
            prev_trigger_pressed=self.left.trigger_pressed,
            prev_grip_pressed=self.left.grip_pressed,
        )
        self.left = self._read_controller(left_id)
        self.left.prev_trackpad_pressed = prev.prev_trackpad_pressed
        self.left.prev_trigger_pressed = prev.prev_trigger_pressed
        self.left.prev_grip_pressed = prev.prev_grip_pressed
        
        # Left stick
        if self.config.stick_on_touch and self.left.trackpad_touched:
            x, y = self._apply_deadzone(self.left.stick_x, self.left.stick_y)
        elif self.left.trackpad_pressed:
            x, y = self._apply_deadzone(self.left.stick_x, self.left.stick_y)
        else:
            x, y = 0.0, 0.0
        
        if self.config.invert_y_left:
            y = -y
        
        self.gamepad.set_stick('left', x, y)
        
        # Left trigger
        self.gamepad.set_trigger('left', self.left.trigger)
        
        # Grip -> LB or back button
        if self.config.grip_as_bumper:
            self.gamepad.set_button('lb', self.left.grip_pressed)
        else:
            self.gamepad.set_button('back_lu', self.left.grip_pressed)
        
        # Menu -> Select
        self.gamepad.set_button('select', self.left.menu_pressed)
        
        # Trackpad click handling
        just_pressed, just_released = self._button_edge('left_pad', self.left.trackpad_pressed)
        
        if self.left.trackpad_pressed:
            if self.config.dpad_on_left:
                # D-pad from trackpad zones
                zone = self.left.stick_zone
                if zone == StickZone.CENTER:
                    # Center click = L3
                    self.gamepad.set_button('ls', True)
                    self.gamepad.set_dpad(0, 0)
                else:
                    self.gamepad.set_button('ls', False)
                    dx = 1 if zone == StickZone.RIGHT else (-1 if zone == StickZone.LEFT else 0)
                    dy = 1 if zone == StickZone.DOWN else (-1 if zone == StickZone.UP else 0)
                    self.gamepad.set_dpad(dx, dy)
                    
                    if just_pressed:
                        self._trigger_haptic(left_id, 0.5)
            else:
                # Just L3 for any click
                self.gamepad.set_button('ls', True)
                
            # Directional stick clicks
            self.gamepad.set_button('ls_up', self.left.stick_zone == StickZone.UP)
            self.gamepad.set_button('ls_down', self.left.stick_zone == StickZone.DOWN)
            self.gamepad.set_button('ls_left', self.left.stick_zone == StickZone.LEFT)
            self.gamepad.set_button('ls_right', self.left.stick_zone == StickZone.RIGHT)
        else:
            self.gamepad.set_button('ls', False)
            self.gamepad.set_dpad(0, 0)
            self.gamepad.set_button('ls_up', False)
            self.gamepad.set_button('ls_down', False)
            self.gamepad.set_button('ls_left', False)
            self.gamepad.set_button('ls_right', False)
    
    def _process_right_controller(self, right_id: int):
        """Process right controller inputs"""
        prev = ControllerState(
            prev_trackpad_pressed=self.right.trackpad_pressed,
            prev_trigger_pressed=self.right.trigger_pressed,
            prev_grip_pressed=self.right.grip_pressed,
        )
        self.right = self._read_controller(right_id)
        self.right.prev_trackpad_pressed = prev.prev_trackpad_pressed
        self.right.prev_trigger_pressed = prev.prev_trigger_pressed
        self.right.prev_grip_pressed = prev.prev_grip_pressed
        
        # Right stick
        if self.config.stick_on_touch and self.right.trackpad_touched:
            x, y = self._apply_deadzone(self.right.stick_x, self.right.stick_y)
        elif self.right.trackpad_pressed:
            x, y = self._apply_deadzone(self.right.stick_x, self.right.stick_y)
        else:
            x, y = 0.0, 0.0
        
        if self.config.invert_y_right:
            y = -y
        
        self.gamepad.set_stick('right', x, y)
        
        # Right trigger
        self.gamepad.set_trigger('right', self.right.trigger)
        
        # Grip -> RB or back button
        if self.config.grip_as_bumper:
            self.gamepad.set_button('rb', self.right.grip_pressed)
        else:
            self.gamepad.set_button('back_ru', self.right.grip_pressed)
        
        # Menu -> Start
        self.gamepad.set_button('start', self.right.menu_pressed)
        
        # System -> Guide
        self.gamepad.set_button('guide', self.right.system_pressed)
        
        # Trackpad click handling
        just_pressed, just_released = self._button_edge('right_pad', self.right.trackpad_pressed)
        
        if self.right.trackpad_pressed:
            if self.config.face_button_zones:
                # Face buttons from trackpad zones
                zone = self.right.stick_zone
                if zone == StickZone.CENTER:
                    # Center click = R3
                    self.gamepad.set_button('rs', True)
                    self.gamepad.set_button('a', False)
                    self.gamepad.set_button('b', False)
                    self.gamepad.set_button('x', False)
                    self.gamepad.set_button('y', False)
                else:
                    self.gamepad.set_button('rs', False)
                    self.gamepad.set_button('a', zone == StickZone.DOWN)
                    self.gamepad.set_button('b', zone == StickZone.RIGHT)
                    self.gamepad.set_button('x', zone == StickZone.LEFT)
                    self.gamepad.set_button('y', zone == StickZone.UP)
                    
                    if just_pressed:
                        self._trigger_haptic(right_id, 0.5)
            else:
                # Just R3 for any click
                self.gamepad.set_button('rs', True)
            
            # Directional stick clicks
            self.gamepad.set_button('rs_up', self.right.stick_zone == StickZone.UP)
            self.gamepad.set_button('rs_down', self.right.stick_zone == StickZone.DOWN)
            self.gamepad.set_button('rs_left', self.right.stick_zone == StickZone.LEFT)
            self.gamepad.set_button('rs_right', self.right.stick_zone == StickZone.RIGHT)
        else:
            self.gamepad.set_button('rs', False)
            self.gamepad.set_button('a', False)
            self.gamepad.set_button('b', False)
            self.gamepad.set_button('x', False)
            self.gamepad.set_button('y', False)
            self.gamepad.set_button('rs_up', False)
            self.gamepad.set_button('rs_down', False)
            self.gamepad.set_button('rs_left', False)
            self.gamepad.set_button('rs_right', False)
    
    def _find_controllers(self):
        """Find left and right controller indices"""
        self._left_id, self._right_id = 'left', 'right'

    def update(self):
        """
        Main update loop - call this every frame.
        Reads VR controller state and updates virtual gamepad.
        """
        self.vrsys.update()
        # Find controllers if not yet found
        if self._left_id is None or self._right_id is None:
            self._find_controllers()
        
        # Process each controller
        if self._left_id is not None:
            self._process_left_controller(self._left_id)
        
        if self._right_id is not None:
            self._process_right_controller(self._right_id)
        
        # Flush all events to the virtual device
        self.gamepad.sync()
    
    def close(self):
        """Clean up resources"""
        self.gamepad.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
