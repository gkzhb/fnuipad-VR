"""
Mapping engine - processes VR input through mapping rules
"""

from _openvr import get_backend
from typing import Dict, Set, Optional
from dataclasses import dataclass, field

from _linuxgamepad import LinuxGamepad
from _mapping import (
    MappingProfile, Mapping, Condition,
    InputType, ConditionType
)


@dataclass
class VRControllerState:
    """Current state of a VR controller"""
    # Buttons (True/False)
    buttons: Dict[str, bool] = field(default_factory=dict)
    # Axes (-1.0 to 1.0 or 0.0 to 1.0)
    axes: Dict[str, float] = field(default_factory=dict)


class MappingEngine:
    """
    Processes VR controller input through mapping rules
    and outputs to virtual gamepad.
    """
    
    def __init__(self, profile: MappingProfile):
        self.profile = profile
        self.vrsys = get_backend()
        self.gamepad = LinuxGamepad(
            name=profile.device_name,
            vendor=profile.device_vendor,
            product=profile.device_product,
        )
        
        # Current controller states
        self.left = VRControllerState()
        self.right = VRControllerState()
        
        # Track which outputs are currently active (for chord handling)
        self._active_outputs: Set[str] = set()
        
        # Track which mappings fired (to prevent double-firing)
        self._fired_mappings: Set[int] = set()
        
        # Controller IDs
        self._left_id: Optional[int] = None
        self._right_id: Optional[int] = None
    
    def _find_controllers(self):
        """Stable hand names; device indices are rediscovered by the backend."""
        self._left_id, self._right_id = 'left', 'right'

    def _read_controller(self, controller_id: str) -> VRControllerState:
        snapshot = self.vrsys.controller(controller_id)
        return VRControllerState(dict(snapshot.buttons), dict(snapshot.axes))
    
    def _get_state(self, controller: str) -> VRControllerState:
        """Get state for a controller by name"""
        return self.left if controller == "left" else self.right
    
    def _get_input_value(self, controller: str, input_type: InputType, input_name: str) -> float:
        """Get the current value of an input"""
        state = self._get_state(controller)
        
        if input_type == InputType.BUTTON:
            return 1.0 if state.buttons.get(input_name, False) else 0.0
        else:
            return state.axes.get(input_name, 0.0)
    
    def _check_condition(self, condition: Condition) -> bool:
        """Check if a condition is met"""
        value = self._get_input_value(
            condition.controller,
            InputType.BUTTON if condition.type in (ConditionType.BUTTON_HELD, ConditionType.BUTTON_NOT_HELD) else InputType.AXIS,
            condition.input_name
        )
        
        if condition.type == ConditionType.BUTTON_HELD:
            return value > 0.5
        elif condition.type == ConditionType.BUTTON_NOT_HELD:
            return value < 0.5
        elif condition.type == ConditionType.AXIS_ABOVE:
            return value > condition.value
        elif condition.type == ConditionType.AXIS_BELOW:
            return value < condition.value
        
        return False
    
    def _check_all_conditions(self, mapping: Mapping) -> bool:
        """Check if all conditions for a mapping are met"""
        for condition in mapping.conditions:
            if not self._check_condition(condition):
                return False
        return True
    
    def _apply_modifiers(self, value: float, mapping: Mapping) -> float:
        """Apply deadzone, sensitivity, invert to a value"""
        # Deadzone
        if abs(value) < mapping.deadzone:
            value = 0.0
        elif mapping.deadzone > 0:
            # Rescale past deadzone
            sign = 1 if value > 0 else -1
            value = sign * (abs(value) - mapping.deadzone) / (1.0 - mapping.deadzone)
        
        # Sensitivity
        value *= mapping.sensitivity
        
        # Invert
        if mapping.invert:
            value = -value
        
        # Clamp
        return max(-1.0, min(1.0, value))
    
    def _set_output(self, output_type: InputType, output_name: str, value: float):
        """Set a gamepad output"""
        if output_type == InputType.BUTTON:
            self.gamepad.set_button(output_name, value > 0.5)
        elif output_type == InputType.AXIS:
            # Map output names to gamepad methods
            if output_name in ("left_stick_x", "axis_1"):
                self._pending_left_x = value
            elif output_name in ("left_stick_y", "axis_2"):
                self._pending_left_y = value
            elif output_name in ("right_stick_x", "axis_4"):
                self._pending_right_x = value
            elif output_name in ("right_stick_y", "axis_5"):
                self._pending_right_y = value
            elif output_name in ("left_trigger", "axis_3"):
                self.gamepad.set_trigger("left", max(0, value))
            elif output_name in ("right_trigger", "axis_6"):
                self.gamepad.set_trigger("right", max(0, value))
            elif output_name in ("dpad_x", "axis_7"):
                self._pending_dpad_x = int(round(value))
            elif output_name in ("dpad_y", "axis_8"):
                self._pending_dpad_y = int(round(value))
    
    def _process_mapping(self, mapping: Mapping) -> bool:
        """
        Process a single mapping.
        Returns True if the mapping was activated (conditions met and input active).
        """
        if not mapping.enabled:
            return False
        
        # Check conditions first
        if not self._check_all_conditions(mapping):
            # Conditions not met - if this was a button, make sure output is released
            if mapping.output_type == InputType.BUTTON:
                self._set_output(mapping.output_type, mapping.output_name, 0.0)
            return False
        
        # Get input value
        value = self._get_input_value(
            mapping.input_controller,
            mapping.input_type,
            mapping.input_name
        )
        
        # Apply modifiers
        value = self._apply_modifiers(value, mapping)
        
        # Set output
        self._set_output(mapping.output_type, mapping.output_name, value)
        
        # Return True if this mapping "consumed" the input
        # (for button: if pressed, for axis: if non-zero)
        if mapping.input_type == InputType.BUTTON:
            return value > 0.5
        else:
            return abs(value) > 0.1
    
    def update(self):
        """Main update - read inputs, process mappings, update gamepad"""
        self.vrsys.update()
        # Find controllers if needed
        if self._left_id is None or self._right_id is None:
            self._find_controllers()
        
        # Read controller states
        if self._left_id is not None:
            self.left = self._read_controller(self._left_id)
        if self._right_id is not None:
            self.right = self._read_controller(self._right_id)
        
        # Reset pending axis values
        self._pending_left_x = 0.0
        self._pending_left_y = 0.0
        self._pending_right_x = 0.0
        self._pending_right_y = 0.0
        self._pending_dpad_x = 0
        self._pending_dpad_y = 0
        
        # Track which inputs have been consumed by higher-priority mappings
        consumed_inputs: Set[tuple] = set()
        
        # Process mappings in priority order (already sorted)
        for mapping in self.profile.mappings:
            input_key = (mapping.input_controller, mapping.input_name)
            
            # Skip if this input was already consumed by a higher-priority chord
            if input_key in consumed_inputs and mapping.conditions:
                continue
            
            if self._process_mapping(mapping):
                # If this was a chord mapping, mark the input as consumed
                if mapping.conditions:
                    consumed_inputs.add(input_key)
        
        # Apply accumulated axis values
        self.gamepad.set_stick("left", self._pending_left_x, self._pending_left_y)
        self.gamepad.set_stick("right", self._pending_right_x, self._pending_right_y)
        self.gamepad.set_dpad(self._pending_dpad_x, self._pending_dpad_y)
        
        # Sync to device
        self.gamepad.sync()
    
    def close(self):
        """Clean up"""
        self.gamepad.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
