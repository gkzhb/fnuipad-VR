"""
VR Steering Wheel Implementation for Linux

Provides a virtual steering wheel that can be grabbed and turned using VR controllers.
Features:
- Single and dual-hand steering (headless, without VR overlays)
- Physics simulation (inertia, centering force, limits)
- Single and dual-hand steering
- Tangential movement calculation for consistent feel

Reimplemented from steam-vr-wheel for Linux/evdev.
"""

from collections import deque
from math import pi, atan2, sin, cos
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
from _openvr import get_backend
import warnings

from _linuxgamepad import LinuxGamepad


# Logitech G29 Racing Wheel identity
G29_VENDOR = 0x046d   # Logitech
G29_PRODUCT = 0xc24f  # G29 Driving Force Racing Wheel
G29_VERSION = 0x0001
G29_NAME = "Logitech G29 Driving Force Racing Wheel"


@dataclass
class Point:
    """3D point in space"""
    x: float
    y: float
    z: float


@dataclass
class GrabControllerPoint(Point):
    """Point with associated controller ID for tracking grabs"""
    id: int = 0


@dataclass
class WheelConfig:
    """Configuration for the steering wheel"""
    # Wheel position (meters from origin)
    wheel_center: Tuple[float, float, float] = (0.0, -0.4, -0.35)

    # Wheel size in meters
    wheel_size: float = 0.35

    # Total rotation range in degrees (e.g., 900 = 2.5 turns lock to lock)
    wheel_degrees: float = 900.0

    # Centering force multiplier (0 = no centering, 1 = normal)
    wheel_centerforce: float = 1.0

    # Whether wheel is vertical (True) or horizontal (False)
    vertical_wheel: bool = True

    # Whether to show the wheel overlay
    wheel_show_wheel: bool = True

    # Whether to show hand overlays
    wheel_show_hands: bool = False

    # Grip mode: True = hold grip to grab, False = toggle grip
    wheel_grabbed_by_grip: bool = True

    # If True, grip must be held; if False, grip toggles grab state
    wheel_grabbed_by_grip_toggle: bool = True

    # Inertia coefficient (0-1, higher = more momentum)
    inertia: float = 0.95

    # Centering speed in radians per frame
    center_speed: float = pi / 18

    # Device identity (default: Logitech G29)
    device_name: str = G29_NAME
    device_vendor: int = G29_VENDOR
    device_product: int = G29_PRODUCT


class Wheel:
    """
    VR Steering Wheel Controller

    Maps VR controller movements to steering wheel input with physics simulation.
    Outputs to a virtual gamepad axis.
    """

    def __init__(self, config: Optional[WheelConfig] = None, gamepad: Optional[LinuxGamepad] = None):
        self.config = config or WheelConfig()

        self.vrsys = get_backend()
        # Create or use provided gamepad with G29 identity by default
        if gamepad is None:
            self.gamepad = LinuxGamepad(
                name=self.config.device_name,
                vendor=self.config.device_vendor,
                product=self.config.device_product,
            )
            self._owns_gamepad = True
        else:
            self.gamepad = gamepad
            self._owns_gamepad = False

        if self.config.wheel_show_wheel or self.config.wheel_show_hands:
            warnings.warn("OpenVR background mode has no VR overlays; display settings are ignored.",
                          RuntimeWarning, stacklevel=2)

        # Wheel state
        x, y, z = self.config.wheel_center
        self.center = Point(x, y, z)
        self.size = self.config.wheel_size

        # Wheel angle tracking (using deque for unwrapping)
        self._wheel_angles = deque(maxlen=10)
        self._wheel_angles.append(0.0)
        self._wheel_angles.append(0.0)

        # Physics state
        self._turn_speed = 0.0  # Current rotation speed (radians/frame)
        self._snapped = False  # Two-hand mode active

        # Grab state
        self._grab_started_point: Optional[GrabControllerPoint] = None
        self._wheel_grab_offset = 0.0
        self._left_controller_grabbed = False
        self._right_controller_grabbed = False
        self._prev_controller_pos: Optional[Point] = None

        # Controller IDs (set on first update)
        self._left_id: Optional[int] = None
        self._right_id: Optional[int] = None

    def _find_controllers(self):
        self._left_id, self._right_id = 'left', 'right'

    def _get_controller_point(self, controller_id: int) -> Point:
        """Get controller position as a Point"""
        m = self.vrsys.controller(controller_id).matrix
        return Point(m[0][3], m[1][3], m[2][3]) if m else Point(0, 0, 0)

    def _get_controller_point_with_id(self, controller_id: int) -> GrabControllerPoint:
        """Get controller position as a GrabControllerPoint with ID"""
        p = self._get_controller_point(controller_id)
        return GrabControllerPoint(p.x, p.y, p.z, controller_id)

    def point_in_holding_bounds(self, point: Point) -> bool:
        """Check if a point is within the wheel's grabbable ring"""
        width = 0.10
        a = self.size / 2 + width
        b = self.size / 2 - width

        if self.config.vertical_wheel:
            x = point.x - self.center.x
            y = point.y - self.center.y
            z = point.z - self.center.z
        else:
            z = point.y - self.center.y
            y = point.x - self.center.x
            x = point.z - self.center.z

        if abs(z) < width:
            distance = (x**2 + y**2)**0.5
            if b < distance < a:
                return True
        return False

    def unwrap_wheel_angles(self):
        """Handle angle wrapping to allow continuous rotation"""
        angles = list(self._wheel_angles)
        unwrapped = angles[0]
        for previous, current in zip(angles, angles[1:]):
            unwrapped += (current - previous + pi) % (2 * pi) - pi
        self._wheel_angles[-1] = unwrapped

    def wheel_raw_angle(self, point: Point) -> float:
        """Calculate raw angle from controller position"""
        if self.config.vertical_wheel:
            a = float(point.y) - self.center.y
            b = float(point.x) - self.center.x
        else:
            a = float(point.x) - self.center.x
            b = float(point.z) - self.center.z
        return atan2(a, b)

    def wheel_tangential_delta(self, current_point: Point, previous_point: Optional[Point]) -> float:
        """
        Calculate angle change using tangential movement.
        This is radius-independent for consistent steering feel.
        """
        if previous_point is None:
            return 0.0

        if self.config.vertical_wheel:
            cx = float(current_point.x) - self.center.x
            cy = float(current_point.y) - self.center.y
            dx = current_point.x - previous_point.x
            dy = current_point.y - previous_point.y
        else:
            cx = float(current_point.x) - self.center.x
            cy = float(current_point.z) - self.center.z
            dx = current_point.x - previous_point.x
            dy = current_point.z - previous_point.z

        radius = (cx**2 + cy**2)**0.5
        if radius < 0.01:
            return 0.0

        # Tangential component perpendicular to radius
        tangential = (-cy * dx + cx * dy) / radius
        angle_delta = tangential / radius

        return angle_delta

    def wheel_double_raw_angle(self, left_ctr: Point, right_ctr: Point) -> float:
        """Calculate angle from two controller positions (two-hand steering)"""
        if self.config.vertical_wheel:
            a = left_ctr.y - right_ctr.y
            b = left_ctr.x - right_ctr.x
        else:
            a = left_ctr.x - right_ctr.x
            b = left_ctr.z - right_ctr.z
        return atan2(a, b)

    def ready_to_unsnap(self, l: Point, r: Point) -> bool:
        """Check if hands have moved apart enough to exit two-hand mode"""
        d = (l.x - r.x)**2 + (l.y - r.y)**2 + (l.z - r.z)**2
        if d > self.size**2:
            return True

        dc = ((self.center.x - (l.x + r.x) / 2)**2 +
              (self.center.y - (l.y + r.y) / 2)**2 +
              (self.center.z - (l.z + r.z) / 2)**2)
        if dc > self.size**2:
            return True

        return False

    def set_button_press(self, button: int, hand: str):
        """Handle button press events"""
        if button == 'grip_click' and hand == 'left':
            if self.config.wheel_grabbed_by_grip_toggle:
                self._left_controller_grabbed = True
            else:
                self._left_controller_grabbed = not self._left_controller_grabbed

        if button == 'grip_click' and hand == 'right':
            if self.config.wheel_grabbed_by_grip_toggle:
                self._right_controller_grabbed = True
            else:
                self._right_controller_grabbed = not self._right_controller_grabbed

        if not (self._right_controller_grabbed and self._left_controller_grabbed):
            self._snapped = False

    def set_button_unpress(self, button: int, hand: str):
        """Handle button release events"""
        if self.config.wheel_grabbed_by_grip_toggle:
            if button == 'grip_click' and hand == 'left':
                self._left_controller_grabbed = False
            if button == 'grip_click' and hand == 'right':
                self._right_controller_grabbed = False

            if not (self._right_controller_grabbed and self._left_controller_grabbed):
                self._snapped = False

    def _wheel_update(self, left_ctr: GrabControllerPoint, right_ctr: GrabControllerPoint) -> Optional[float]:
        """Update wheel angle based on controller positions"""
        if self.config.wheel_grabbed_by_grip:
            left_bound = self._left_controller_grabbed
            right_bound = self._right_controller_grabbed
        else:
            # Automatic gripping
            right_bound = self.point_in_holding_bounds(right_ctr)
            left_bound = self.point_in_holding_bounds(left_ctr)
            if self.ready_to_unsnap(left_ctr, right_ctr):
                self._snapped = False

        # Check for two-hand grab
        if right_bound and left_bound and not self._snapped:
            self._is_held([left_ctr, right_ctr])

        if self._snapped:
            angle = self.wheel_double_raw_angle(left_ctr, right_ctr) + self._wheel_grab_offset
            return angle

        # Single controller steering
        if right_bound:
            controller = right_ctr
            self._is_held(controller)
        elif left_bound:
            controller = left_ctr
            self._is_held(controller)
        else:
            self._is_not_held()
            self._prev_controller_pos = None
            return None

        # Use tangential delta for consistent feel
        angle_delta = self.wheel_tangential_delta(controller, self._prev_controller_pos)
        self._prev_controller_pos = Point(controller.x, controller.y, controller.z)

        if angle_delta != 0:
            return self._wheel_angles[-1] + angle_delta
        return self._wheel_angles[-1]

    def calculate_grab_offset(self, raw_angle: Optional[float] = None):
        """Calculate offset to maintain wheel position when grabbing"""
        if raw_angle is None:
            raw_angle = self.wheel_raw_angle(self._grab_started_point)
        self._wheel_grab_offset = self._wheel_angles[-1] - raw_angle

    def _is_held(self, controller):
        """Handle wheel being held"""
        if isinstance(controller, list):
            # Two-hand mode
            self._snapped = True
            angle = self.wheel_double_raw_angle(controller[0], controller[1])
            self.calculate_grab_offset(angle)
            self._grab_started_point = None
            self._prev_controller_pos = None
            return

        if self._grab_started_point is None or self._grab_started_point.id != controller.id:
            self._grab_started_point = GrabControllerPoint(
                controller.x, controller.y, controller.z, controller.id
            )
            self._prev_controller_pos = Point(controller.x, controller.y, controller.z)

    def _is_not_held(self):
        """Handle wheel being released"""
        self._grab_started_point = None
        self._prev_controller_pos = None

    def inertia(self):
        """Apply inertia physics to wheel rotation"""
        if self._grab_started_point:
            # Track turn speed while held
            self._turn_speed = self._wheel_angles[-1] - self._wheel_angles[-2]
        else:
            max_angle = (self.config.wheel_degrees / 360) * pi
            is_overturned = abs(self._wheel_angles[-1]) > max_angle

            if is_overturned:
                # Return to valid range when overturned
                over_amount = abs(self._wheel_angles[-1]) - max_angle
                over_ratio = min(over_amount / (max_angle * 0.2), 1.0)
                sign = -1 if self._wheel_angles[-1] > 0 else 1
                return_speed = 0.01 + (over_ratio * 0.02)

                if abs(self._turn_speed * sign) < return_speed:
                    self._turn_speed = sign * return_speed

            self._wheel_angles.append(self._wheel_angles[-1] + self._turn_speed)

            # Apply inertia decay
            if not is_overturned:
                self._turn_speed *= self.config.inertia
            else:
                self._turn_speed *= self.config.inertia * 0.95

    def center_force(self):
        """Apply centering force to return wheel to center"""
        angle = self._wheel_angles[-1]
        sign = 1 if angle >= 0 else -1

        max_angle = (self.config.wheel_degrees / 360) * pi
        is_overturned = abs(angle) > max_angle

        base_center_force = self.config.center_speed * self.config.wheel_centerforce

        if is_overturned:
            center_force = base_center_force * 1.5
        else:
            center_force = base_center_force
            limit_factor = abs(angle) / max_angle
            if limit_factor > 0.7:
                center_force *= (1 + (limit_factor - 0.7) * 0.8)

        if abs(angle) < center_force:
            self._wheel_angles[-1] = 0
            return

        self._wheel_angles[-1] -= center_force * sign

    def limiter(self, left_ctr: GrabControllerPoint, right_ctr: GrabControllerPoint):
        """Apply limits to wheel rotation with haptic feedback"""
        max_angle = (self.config.wheel_degrees / 360) * pi

        if abs(self._wheel_angles[-1]) > max_angle:
            over_angle = abs(self._wheel_angles[-1]) - max_angle
            sign = 1 if self._wheel_angles[-1] > 0 else -1

            # Elastic resistance
            elasticity = 0.25
            allowed_over = max_angle + (over_angle * elasticity)
            self._wheel_angles[-1] = sign * min(abs(self._wheel_angles[-1]), allowed_over)

            # Haptic feedback
            base_haptic = 1500
            haptic_intensity = min(int(base_haptic + (over_angle * 2500)), 3999)

            if abs(self._wheel_angles[-1] - self._wheel_angles[-2]) > 0.015:
                self.vrsys.haptic(left_ctr.id, duration_ns=haptic_intensity * 1000)
                self.vrsys.haptic(right_ctr.id, duration_ns=haptic_intensity * 1000)

    def send_to_gamepad(self):
        """Send wheel position to virtual gamepad"""
        wheel_turn = self._wheel_angles[-1] / (2 * pi)
        # Map to -1.0 to 1.0 range
        axis_value = -wheel_turn / (self.config.wheel_degrees / 360)
        axis_value = max(-1.0, min(1.0, axis_value))

        # Send to left stick X axis (steering)
        self.gamepad.set_stick('left', axis_value, 0)
        self.gamepad.sync()

    def _wheel_update_common(self, angle: Optional[float],
                              left_ctr: GrabControllerPoint, right_ctr: GrabControllerPoint):
        """Common wheel update logic"""
        if angle is not None:
            self._wheel_angles.append(angle)

        self.unwrap_wheel_angles()
        self.limiter(left_ctr, right_ctr)
        self.inertia()

        # Apply centering when not held
        if not self._left_controller_grabbed and not self._right_controller_grabbed:
            self.center_force()

        self.send_to_gamepad()

    def _read_controller_buttons(self, controller_id: int) -> Tuple[bool, bool]:
        """Read grip and trigger state from controller"""
        buttons = self.vrsys.controller(controller_id).buttons
        return buttons.get('grip_click', False), buttons.get('trigger_click', False)

    def update(self):
        """Main update loop - call every frame"""
        self.vrsys.update()
        # Find controllers if needed
        if self._left_id is None or self._right_id is None:
            self._find_controllers()

        if self._left_id is None or self._right_id is None:
            return

        if not all(self.vrsys.controller(hand).pose_valid for hand in ('left', 'right')):
            self._left_controller_grabbed = self._right_controller_grabbed = False
            self._snapped = False
            self._grab_started_point = self._prev_controller_pos = None
            self._turn_speed = 0.0
            self.gamepad.set_stick('left', 0.0, 0.0)
            self.gamepad.sync()
            return

        # Get controller positions
        left_ctr = self._get_controller_point_with_id(self._left_id)
        right_ctr = self._get_controller_point_with_id(self._right_id)

        # Read button states
        left_grip, left_trigger = self._read_controller_buttons(self._left_id)
        right_grip, right_trigger = self._read_controller_buttons(self._right_id)

        # Update grip states
        if self.config.wheel_grabbed_by_grip:
            if left_grip != self._left_controller_grabbed:
                if left_grip:
                    self.set_button_press('grip_click', 'left')
                else:
                    self.set_button_unpress('grip_click', 'left')

            if right_grip != self._right_controller_grabbed:
                if right_grip:
                    self.set_button_press('grip_click', 'right')
                else:
                    self.set_button_unpress('grip_click', 'right')

        # Update wheel angle
        angle = self._wheel_update(left_ctr, right_ctr)
        self._wheel_update_common(angle, left_ctr, right_ctr)

    def move_wheel(self, right_ctr: Point, left_ctr: Point):
        """Move wheel to new position (edit mode)"""
        self.center = Point(right_ctr.x, right_ctr.y, right_ctr.z)
        self.config.wheel_center = (self.center.x, self.center.y, self.center.z)

        size = ((right_ctr.x - left_ctr.x)**2 +
                (right_ctr.y - left_ctr.y)**2 +
                (right_ctr.z - left_ctr.z)**2)**0.5 * 2
        self.config.wheel_size = size
        self.size = size

    def edit_mode(self):
        """Calibrate anchors in LOCAL space without an overlay."""
        self.vrsys.update()
        self._find_controllers()
        if not all(self.vrsys.controller(hand).pose_valid for hand in ('left', 'right')):
            return
        if self.vrsys.controller('right').buttons.get('trigger_click', False):
            self.move_wheel(self._get_controller_point('right'), self._get_controller_point('left'))

    def close(self):
        """Clean up resources"""
        if self._owns_gamepad and self.gamepad:
            self.gamepad.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
