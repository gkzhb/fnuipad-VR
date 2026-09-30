"""
VR Flight Stick (Stick Yoke) + Throttle Implementation for Linux

Provides a virtual flight stick anchored at a point (simulating floor mount).
Features:
- Stick yoke anchored at a configurable point
- Push/pull for pitch (elevator)
- Left/right tilt for roll (ailerons)
- Twist for rudder (yaw)
- Throttle on separate controller (left hand)
- Background OpenVR tracking (no VR visualization)
"""

from collections import deque
from math import pi, atan2, sin, cos, sqrt, asin
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import time

from _openvr import get_backend
import warnings

from _linuxgamepad import LinuxGamepad


# Honeycomb Aeronautical Alpha Flight Controls (extremely popular yoke)
HONEYCOMB_VENDOR = 0x294B   # Honeycomb Aeronautical
HONEYCOMB_PRODUCT = 0x1901  # Alpha Yoke
HONEYCOMB_VERSION = 0x0001
HONEYCOMB_NAME = "Honeycomb Alpha Flight Controls"

# Thrustmaster TCA Yoke (Airbus edition, also very popular)
TCA_VENDOR = 0x044F   # Thrustmaster
TCA_PRODUCT = 0xB6B4  # TCA Yoke Boeing Edition
TCA_VERSION = 0x0001
TCA_NAME = "Thrustmaster TCA Yoke Boeing"

# Generic joystick identity
GENERIC_VENDOR = 0x1234
GENERIC_PRODUCT = 0xBEAD
GENERIC_VERSION = 0x0001
GENERIC_NAME = "VR Flight Stick"


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
class FlightStickConfig:
    """Configuration for the flight stick and throttle"""

    # Stick anchor point (BASE of stick - should be below floor level)
    # In seated tracking space, Y=0 is roughly seat level, negative is down
    # With 0.7m stick, base at -1.2 puts grip at -0.5 (knee height)
    stick_anchor: Tuple[float, float, float] = (0.0, -1.2, -0.35)

    # Stick length in meters (classic yoke style - longer than FBW sidestick)
    stick_length: float = 0.7

    # Maximum deflection angle in degrees for pitch/roll
    # Lower = tighter/less movement needed for full deflection
    max_deflection_degrees: float = 15.0

    # Maximum twist angle in degrees for rudder
    max_twist_degrees: float = 45.0

    # Deadzone for stick axes (0-1)
    stick_deadzone: float = 0.05

    # Deadzone for rudder twist (0-1)
    rudder_deadzone: float = 0.08

    # Sensitivity multipliers
    pitch_sensitivity: float = 1.0
    roll_sensitivity: float = 1.0
    rudder_sensitivity: float = 1.0

    # Invert axes if needed
    invert_pitch: bool = False  # True = pull back for nose up
    invert_roll: bool = False
    invert_rudder: bool = True

    # Throttle configuration
    # Throttle anchor (left hand rest position)
    throttle_anchor: Tuple[float, float, float] = (-0.3, -0.4, -0.3)

    # Throttle range in meters (vertical movement)
    throttle_range: float = 0.3

    # Throttle deadzone
    throttle_deadzone: float = 0.02

    # Center lerp speed for stick return (0 = no return, higher = faster)
    # This is multiplied by delta time, so 2.0 means ~2 seconds to center
    stick_center_lerp: float = 3.0

    # Grab radius - how close controller must be to stick grip to grab (meters)
    stick_grab_radius: float = 0.15

    # Throttle grab radius
    throttle_grab_radius: float = 0.12

    # Whether to show VR overlays
    show_stick: bool = True
    show_throttle: bool = True

    # Grip behavior
    stick_grabbed_by_grip: bool = True
    stick_grabbed_by_grip_toggle: bool = True  # Hold vs toggle
    throttle_grabbed_by_grip: bool = True
    throttle_grabbed_by_grip_toggle: bool = True

    # Device identity (default: Honeycomb Alpha - widely supported in flight sims)
    device_name: str = HONEYCOMB_NAME
    device_vendor: int = HONEYCOMB_VENDOR
    device_product: int = HONEYCOMB_PRODUCT


class FlightStick:
    """
    VR Flight Stick (Stick Yoke) + Throttle Controller

    Maps VR controller movements to flight stick axes:
    - Right controller: Stick yoke (pitch, roll, rudder twist)
    - Left controller: Throttle

    The stick is "anchored" at a point simulating a floor-mounted stick.
    Deflection from the anchor determines pitch and roll.
    Twisting the controller determines rudder.
    """

    def __init__(self, config: Optional[FlightStickConfig] = None,
                 gamepad: Optional[LinuxGamepad] = None):
        self.config = config or FlightStickConfig()

        self.vrsys = get_backend()
        # Create or use provided gamepad
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

        if self.config.show_stick or self.config.show_throttle:
            warnings.warn("OpenVR background mode has no VR overlays; display settings are ignored.",
                          RuntimeWarning, stacklevel=2)

        # Anchor points
        x, y, z = self.config.stick_anchor
        self.stick_anchor = Point(x, y, z)

        tx, ty, tz = self.config.throttle_anchor
        self.throttle_anchor = Point(tx, ty, tz)

        # Current axis values
        self._pitch = 0.0      # -1 to 1 (nose down to nose up)
        self._roll = 0.0       # -1 to 1 (left to right)
        self._rudder = 0.0     # -1 to 1 (left to right yaw)
        self._throttle = 0.0   # 0 to 1

        # Grab state
        self._stick_grabbed = False
        self._throttle_grabbed = False

        # Controller orientation at grab start (for twist calculation)
        self._grab_start_yaw: Optional[float] = None
        self._grab_yaw_offset: float = 0.0

        # Throttle grab start position (Z axis - forward/back)
        self._throttle_grab_start_z: Optional[float] = None
        self._throttle_grab_offset: float = 0.0

        # Controller IDs
        self._left_id: Optional[int] = None
        self._right_id: Optional[int] = None

        # Previous button states for edge detection
        self._prev_right_grip = False
        self._prev_left_grip = False

        # Frame timing for lerp
        self._last_update_time: Optional[float] = None

    def _find_controllers(self):
        self._left_id, self._right_id = 'left', 'right'

    def _get_controller_pose(self, controller_id: int):
        """Get controller position and rotation matrix"""
        m = self.vrsys.controller(controller_id).matrix
        if m is not None:
            return Point(m[0][3], m[1][3], m[2][3]), m
        return Point(0, 0, 0), None

    def _get_controller_point(self, controller_id: int) -> Point:
        """Get controller position as a Point"""
        pos, _ = self._get_controller_pose(controller_id)
        return pos

    def _get_controller_yaw(self, rotation_matrix) -> float:
        """
        Extract yaw (rotation around Y axis) from controller rotation matrix.
        This is used for rudder twist detection.
        """
        if rotation_matrix is None:
            return 0.0

        # Extract yaw from rotation matrix
        # The rotation matrix columns are the rotated basis vectors
        # For yaw around Y, we look at the X and Z components of the forward vector

        # Forward vector is the negative Z column (OpenVR convention)
        forward_x = -rotation_matrix[0][2]
        forward_z = -rotation_matrix[2][2]

        yaw = atan2(forward_x, forward_z)
        return yaw

    def _get_controller_roll(self, rotation_matrix) -> float:
        """
        Extract roll (rotation around Z axis) from controller rotation matrix.
        This is used for rudder twist when holding the stick.
        """
        if rotation_matrix is None:
            return 0.0

        # For twist/roll around the controller's forward axis,
        # we look at the orientation of the "up" vector in the local frame
        up_x = rotation_matrix[0][1]
        up_y = rotation_matrix[1][1]
        up_z = rotation_matrix[2][1]

        # Project onto the XZ plane and get angle
        roll = atan2(up_x, up_y)
        return roll

    def _read_controller_buttons(self, controller_id: int) -> Tuple[bool, bool]:
        """Read grip and trigger state from controller"""
        buttons = self.vrsys.controller(controller_id).buttons
        return buttons.get('grip_click', False), buttons.get('trigger_click', False)

    def _get_stick_grip_position(self) -> Point:
        """
        Calculate the current position of the stick grip based on current deflection.
        The grip is at the top of the stick, which tilts based on pitch/roll.
        """
        # Convert current axis values to angles
        max_angle = self.config.max_deflection_degrees * pi / 180.0
        pitch_angle = self._pitch * max_angle
        roll_angle = self._roll * max_angle

        # The grip is at stick_length distance from anchor
        length = self.config.stick_length

        # Calculate rotated position (stick tilts from anchor)
        # Roll rotates around Z, Pitch rotates around X
        # Start with vertical stick pointing up
        grip_x = self.stick_anchor.x + length * sin(roll_angle)
        grip_y = self.stick_anchor.y + length * cos(roll_angle) * cos(pitch_angle)
        grip_z = self.stick_anchor.z - length * sin(pitch_angle)

        return Point(grip_x, grip_y, grip_z)

    def _get_throttle_position(self) -> Point:
        """Get current throttle lever position"""
        return Point(
            self.throttle_anchor.x,
            self.throttle_anchor.y,
            self.throttle_anchor.z - self._throttle * self.config.throttle_range  # Forward = more throttle
        )

    def _is_near_stick_grip(self, controller_pos: Point) -> bool:
        """Check if controller is close enough to the stick grip to grab it"""
        grip_pos = self._get_stick_grip_position()
        dx = controller_pos.x - grip_pos.x
        dy = controller_pos.y - grip_pos.y
        dz = controller_pos.z - grip_pos.z
        distance = sqrt(dx*dx + dy*dy + dz*dz)
        return distance <= self.config.stick_grab_radius

    def _is_near_throttle(self, controller_pos: Point) -> bool:
        """Check if controller is close enough to the throttle to grab it"""
        throttle_pos = self._get_throttle_position()
        dx = controller_pos.x - throttle_pos.x
        dy = controller_pos.y - throttle_pos.y
        dz = controller_pos.z - throttle_pos.z
        distance = sqrt(dx*dx + dy*dy + dz*dz)
        return distance <= self.config.throttle_grab_radius

    def _apply_deadzone(self, value: float, deadzone: float) -> float:
        """Apply deadzone to axis value"""
        if abs(value) < deadzone:
            return 0.0

        # Rescale to maintain full range after deadzone
        sign = 1 if value > 0 else -1
        return sign * (abs(value) - deadzone) / (1.0 - deadzone)

    def _calculate_stick_deflection(self, controller_pos: Point) -> Tuple[float, float]:
        """
        Calculate pitch and roll from controller position relative to anchor.

        The stick anchor represents where the physical stick would be mounted.
        The controller position relative to this anchor determines deflection.
        """
        # Vector from anchor to controller
        dx = controller_pos.x - self.stick_anchor.x
        dy = controller_pos.y - self.stick_anchor.y
        dz = controller_pos.z - self.stick_anchor.z

        # Distance from anchor
        dist = sqrt(dx*dx + dy*dy + dz*dz)

        if dist < 0.01:  # Too close to anchor
            return 0.0, 0.0

        # Normalize to stick length for consistent feel
        stick_length = self.config.stick_length

        # Calculate angles
        # Pitch: forward/back tilt (based on Z displacement at the grip height)
        # Roll: left/right tilt (based on X displacement at the grip height)

        # The controller should be roughly at stick_length above the anchor
        # The tilt is the angle from vertical

        max_deflection_rad = self.config.max_deflection_degrees * pi / 180.0

        # Pitch: forward = nose down, back = nose up
        # Use atan2 to get angle from vertical
        pitch_angle = atan2(-dz, dy)  # Negative Z = forward in seated space
        pitch_normalized = pitch_angle / max_deflection_rad
        pitch_normalized = max(-1.0, min(1.0, pitch_normalized))

        # Roll: left = left tilt, right = right tilt
        roll_angle = atan2(dx, dy)
        roll_normalized = roll_angle / max_deflection_rad
        roll_normalized = max(-1.0, min(1.0, roll_normalized))

        return pitch_normalized, roll_normalized

    def _calculate_rudder_twist(self, rotation_matrix) -> float:
        """
        Calculate rudder from controller twist (rotation around stick axis).
        """
        current_roll = self._get_controller_roll(rotation_matrix)

        if self._grab_start_yaw is None:
            self._grab_start_yaw = current_roll
            return self._rudder  # Keep current value

        # Calculate twist relative to grab start
        twist = current_roll - self._grab_start_yaw + self._grab_yaw_offset

        # Normalize twist angle (handle wrap-around)
        while twist > pi:
            twist -= 2 * pi
        while twist < -pi:
            twist += 2 * pi

        max_twist_rad = self.config.max_twist_degrees * pi / 180.0
        rudder = twist / max_twist_rad
        rudder = max(-1.0, min(1.0, rudder))

        return rudder

    def _calculate_throttle(self, controller_pos: Point) -> float:
        """
        Calculate throttle from controller Z position (forward/backward).
        Forward = more throttle, backward = less throttle.
        """
        if self._throttle_grab_start_z is None:
            self._throttle_grab_start_z = controller_pos.z
            return self._throttle

        # Calculate position change since grab (negative Z = forward = more throttle)
        delta_z = self._throttle_grab_start_z - controller_pos.z

        # Add to offset from grab start
        throttle = self._throttle_grab_offset + (delta_z / self.config.throttle_range)
        throttle = max(0.0, min(1.0, throttle))

        return throttle

    def _update_stick(self, right_ctr: Point, right_rotation, delta_time: float):
        """Update stick axes from right controller"""
        if not self._stick_grabbed:
            # Lerp back to center when not grabbed
            if self.config.stick_center_lerp > 0:
                lerp_factor = min(1.0, self.config.stick_center_lerp * delta_time)
                self._pitch = self._pitch * (1.0 - lerp_factor)
                self._roll = self._roll * (1.0 - lerp_factor)
                self._rudder = self._rudder * (1.0 - lerp_factor)
                # Snap to zero when very close
                if abs(self._pitch) < 0.001:
                    self._pitch = 0.0
                if abs(self._roll) < 0.001:
                    self._roll = 0.0
                if abs(self._rudder) < 0.001:
                    self._rudder = 0.0
            return

        # Calculate pitch and roll from stick deflection
        pitch, roll = self._calculate_stick_deflection(right_ctr)

        # Apply sensitivity
        pitch *= self.config.pitch_sensitivity
        roll *= self.config.roll_sensitivity

        # Apply deadzone
        pitch = self._apply_deadzone(pitch, self.config.stick_deadzone)
        roll = self._apply_deadzone(roll, self.config.stick_deadzone)

        # Apply inversion
        if self.config.invert_pitch:
            pitch = -pitch
        if self.config.invert_roll:
            roll = -roll

        self._pitch = pitch
        self._roll = roll

        # Calculate rudder from twist
        rudder = self._calculate_rudder_twist(right_rotation)
        rudder *= self.config.rudder_sensitivity
        rudder = self._apply_deadzone(rudder, self.config.rudder_deadzone)

        if self.config.invert_rudder:
            rudder = -rudder

        self._rudder = rudder

    def _update_throttle(self, left_ctr: Point):
        """Update throttle from left controller"""
        if not self._throttle_grabbed:
            return

        throttle = self._calculate_throttle(left_ctr)
        throttle = self._apply_deadzone(throttle, self.config.throttle_deadzone)
        self._throttle = throttle

    def _handle_grip_press(self, hand: str, controller_pos: Point):
        """Handle grip button press - only grab if controller is near the grip"""
        if hand == 'right':
            # Only allow grab if near the stick grip
            if not self._is_near_stick_grip(controller_pos):
                return  # Too far from grip, do nothing

            if self.config.stick_grabbed_by_grip_toggle:
                self._stick_grabbed = True
            else:
                self._stick_grabbed = not self._stick_grabbed

            if self._stick_grabbed:
                # Reset grab start for twist calculation
                self._grab_start_yaw = None
                self._grab_yaw_offset = self._rudder * (self.config.max_twist_degrees * pi / 180.0)

        elif hand == 'left':
            # Only allow grab if near the throttle
            if not self._is_near_throttle(controller_pos):
                return  # Too far from throttle, do nothing

            if self.config.throttle_grabbed_by_grip_toggle:
                self._throttle_grabbed = True
            else:
                self._throttle_grabbed = not self._throttle_grabbed

            if self._throttle_grabbed:
                self._throttle_grab_start_z = None
                self._throttle_grab_offset = self._throttle

    def _handle_grip_release(self, hand: str):
        """Handle grip button release"""
        if hand == 'right' and self.config.stick_grabbed_by_grip_toggle:
            self._stick_grabbed = False
            self._grab_start_yaw = None

        elif hand == 'left' and self.config.throttle_grabbed_by_grip_toggle:
            self._throttle_grabbed = False
            self._throttle_grab_start_z = None

    def send_to_gamepad(self):
        """Send axis values to virtual gamepad"""
        # Pitch -> Right stick Y (elevator)
        # Roll -> Right stick X (ailerons)
        # Rudder -> Left stick X (yaw)
        # Throttle -> Left trigger or axis

        self.gamepad.set_stick('right', self._roll, self._pitch)
        # Throttle: convert 0-1 range to -1 to 1 for full axis range
        # 0% throttle = -1, 100% throttle = 1
        throttle_axis = (self._throttle * 2.0) - 1.0
        self.gamepad.set_stick('left', self._rudder, throttle_axis)
        self.gamepad.sync()

    def update(self):
        """Main update loop - call every frame"""
        self.vrsys.update()
        # Calculate delta time
        current_time = time.perf_counter()
        if self._last_update_time is None:
            delta_time = 1.0 / 90.0  # Assume 90Hz on first frame
        else:
            delta_time = current_time - self._last_update_time
        self._last_update_time = current_time

        # Find controllers if needed
        if self._left_id is None or self._right_id is None:
            self._find_controllers()

        if self._left_id is None or self._right_id is None:
            return

        if not all(self.vrsys.controller(hand).pose_valid for hand in ('left', 'right')):
            self._stick_grabbed = self._throttle_grabbed = False
            self._prev_left_grip = self._prev_right_grip = False
            self._grab_start_yaw = self._throttle_grab_start_z = None
            self._pitch = self._roll = self._rudder = self._throttle = 0.0
            self.send_to_gamepad()
            return

        # Get controller positions and rotations
        right_pos, right_rotation = self._get_controller_pose(self._right_id)
        left_pos, _ = self._get_controller_pose(self._left_id)

        # Read button states
        right_grip, right_trigger = self._read_controller_buttons(self._right_id)
        left_grip, left_trigger = self._read_controller_buttons(self._left_id)

        # Handle grip state changes (edge detection)
        if self.config.stick_grabbed_by_grip:
            if right_grip and not self._prev_right_grip:
                self._handle_grip_press('right', right_pos)
            elif not right_grip and self._prev_right_grip:
                self._handle_grip_release('right')

        if self.config.throttle_grabbed_by_grip:
            if left_grip and not self._prev_left_grip:
                self._handle_grip_press('left', left_pos)
            elif not left_grip and self._prev_left_grip:
                self._handle_grip_release('left')

        self._prev_right_grip = right_grip
        self._prev_left_grip = left_grip

        # Update axes
        self._update_stick(right_pos, right_rotation, delta_time)
        self._update_throttle(left_pos)

        # Send to gamepad
        self.send_to_gamepad()

    def edit_mode(self):
        """Calibrate anchors in LOCAL space without an overlay."""
        self.vrsys.update()
        self._find_controllers()
        if not all(self.vrsys.controller(hand).pose_valid for hand in ('left', 'right')):
            return
        for hand, anchor in [('right', 'stick_anchor'), ('left', 'throttle_anchor')]:
            if self.vrsys.controller(hand).buttons.get('trigger_click', False):
                pos = self._get_controller_point(hand)
                setattr(self, anchor, pos)
                setattr(self.config, anchor, (pos.x, pos.y, pos.z))

    def get_axis_values(self) -> dict:
        """Get current axis values for debugging/display"""
        return {
            'pitch': self._pitch,
            'roll': self._roll,
            'rudder': self._rudder,
            'throttle': self._throttle,
            'stick_grabbed': self._stick_grabbed,
            'throttle_grabbed': self._throttle_grabbed,
        }

    def close(self):
        """Clean up resources"""
        if self._owns_gamepad and self.gamepad:
            self.gamepad.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
