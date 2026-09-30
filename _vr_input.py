"""Runtime-independent input snapshots shared by the OpenXR consumers."""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class ControllerInput:
    buttons: Dict[str, bool] = field(default_factory=dict)
    axes: Dict[str, float] = field(default_factory=dict)
    # Row-major 3x4 transform in LOCAL space (meters, +Y up, -Z forward).
    matrix: Optional[Tuple[Tuple[float, ...], ...]] = None

    @property
    def pose_valid(self):
        return self.matrix is not None


def pose_matrix(pose):
    """Convert an OpenXR unit quaternion and position to a rigid transform."""
    x, y, z, w = pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w
    p = pose.position
    return (
        (1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w), p.x),
        (2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w), p.y),
        (2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y), p.z),
    )
