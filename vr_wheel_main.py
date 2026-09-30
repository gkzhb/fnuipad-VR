#!/usr/bin/env python3
"""
VR Steering Wheel - Main entry point

Runs the VR steering wheel simulator.
Requires SteamVR; connects as an OpenVR Background application.

Usage:
    python vr_wheel_main.py                    # Run with default settings
    python vr_wheel_main.py --degrees 540      # Set rotation range
    python vr_wheel_main.py --no-wheel         # Hide wheel overlay
    python vr_wheel_main.py --edit             # Enter edit mode to position wheel
"""

import sys
import time
import signal
import argparse
from dataclasses import asdict

import _openvr as vr_backend

from _wheel import Wheel, WheelConfig, G29_NAME, G29_VENDOR, G29_PRODUCT


class WheelApplication:
    def __init__(self, config: WheelConfig, edit_mode: bool = False):
        self.running = True
        self.config = config
        self.edit_mode = edit_mode
        self.wheel = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print("\nShutting down...")
        self.running = False

    def run(self):
        print("VR Steering Wheel")
        print("=" * 50)
        print(f"Device: {self.config.device_name}")
        print(f"VID:PID: {self.config.device_vendor:04x}:{self.config.device_product:04x}")
        print(f"Rotation range: {self.config.wheel_degrees}°")
        print(f"Wheel size: {self.config.wheel_size:.2f}m")
        print(f"Center force: {self.config.wheel_centerforce}")
        print(f"Inertia: {self.config.inertia}")
        print()

        # Never acquire the foreground VR scene.
        print("Initializing OpenVR Background...")
        try:
            vr_backend.init()
        except vr_backend.OpenVRError as e:
            print(f"Error: Could not initialize OpenVR Background: {e}")
            print("Check that SteamVR is running and controllers are connected.")
            return 1

        print("OpenVR Background initialized")
        print()

        # Create wheel
        print("Creating virtual steering wheel...")
        try:
            self.wheel = Wheel(config=self.config)
        except Exception as e:
            print(f"Error creating wheel: {e}")
            print()
            print("Make sure you have permissions for /dev/uinput:")
            print("  sudo usermod -aG input $USER")
            print("  sudo modprobe uinput")
            vr_backend.shutdown()
            return 1

        print("Steering wheel created")
        print()

        if self.edit_mode:
            print("EDIT MODE")
            print("-" * 50)
            print("Point right controller at wheel position")
            print("Hold trigger to set wheel position and size")
            print("Left controller sets the wheel diameter")
            print("Press Ctrl+C when done")
            print("-" * 50)
        else:
            print("Controls:")
            print("-" * 50)
            print("  Grip button - Grab the wheel")
            print("  Move hand tangentially - Turn wheel")
            print("  Two hands - More precise steering")
            print("-" * 50)

        print()
        print("Running... Press Ctrl+C to stop")
        print()

        # Target ~90Hz
        frame_time = 1.0 / 90.0

        try:
            while self.running:
                start = time.perf_counter()

                try:
                    if self.edit_mode:
                        self.wheel.edit_mode()
                    else:
                        self.wheel.update()
                except vr_backend.SessionEnded as e:
                    print(e)
                    return 0
                except vr_backend.OpenVRError as e:
                    print(f"OpenVR error: {e}")
                    return 1

                elapsed = time.perf_counter() - start
                sleep_time = frame_time - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        finally:
            print("Cleaning up...")
            if self.wheel:
                # Print final config if in edit mode
                if self.edit_mode:
                    print()
                    print("Final wheel configuration:")
                    print(f"  wheel_center: {self.config.wheel_center}")
                    print(f"  wheel_size: {self.config.wheel_size:.3f}")
                self.wheel.close()
            vr_backend.shutdown()
            print("Done")

        return 0


def main():
    parser = argparse.ArgumentParser(
        description="VR Steering Wheel Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                        Run with default settings
  %(prog)s --degrees 540          Use 540° rotation (1.5 turns)
  %(prog)s --degrees 900          Use 900° rotation (2.5 turns)
  %(prog)s --no-wheel             Hide wheel overlay
  %(prog)s --hands                Show hand overlays
  %(prog)s --edit                 Position the wheel in VR

Wheel Physics:
  --inertia 0.95                 Momentum when released (0-1)
  --centerforce 1.0              Self-centering strength (0-2)
  --horizontal                   Horizontal wheel (like a boat)
        """
    )

    # Wheel settings
    parser.add_argument(
        '--degrees', '-d',
        type=float,
        default=900.0,
        help='Total rotation range in degrees (default: 900)'
    )
    parser.add_argument(
        '--size',
        type=float,
        default=0.35,
        help='Wheel diameter in meters (default: 0.35)'
    )
    parser.add_argument(
        '--center',
        type=float,
        nargs=3,
        metavar=('X', 'Y', 'Z'),
        default=[0.0, -0.4, -0.35],
        help='Wheel center position (default: 0 -0.4 -0.35)'
    )

    # Physics
    parser.add_argument(
        '--inertia',
        type=float,
        default=0.95,
        help='Wheel inertia (0-1, default: 0.95)'
    )
    parser.add_argument(
        '--centerforce',
        type=float,
        default=1.0,
        help='Centering force multiplier (default: 1.0)'
    )

    # Display options
    parser.add_argument(
        '--no-wheel',
        action='store_true',
        help='Hide wheel overlay'
    )
    parser.add_argument(
        '--hands',
        action='store_true',
        help='Show hand overlays (off by default)'
    )
    parser.add_argument(
        '--horizontal',
        action='store_true',
        help='Use horizontal wheel orientation'
    )

    # Grip mode
    parser.add_argument(
        '--auto-grip',
        action='store_true',
        help='Auto-grip when hands are near wheel (no grip button needed)'
    )
    parser.add_argument(
        '--toggle-grip',
        action='store_true',
        help='Toggle grip on/off with grip button (instead of hold)'
    )

    # Special modes
    parser.add_argument(
        '--edit',
        action='store_true',
        help='Enter edit mode to position the wheel'
    )

    args = parser.parse_args()

    # Build config
    config = WheelConfig(
        wheel_center=tuple(args.center),
        wheel_size=args.size,
        wheel_degrees=args.degrees,
        wheel_centerforce=args.centerforce,
        vertical_wheel=not args.horizontal,
        wheel_show_wheel=not args.no_wheel,
        wheel_show_hands=args.hands,
        wheel_grabbed_by_grip=not args.auto_grip,
        wheel_grabbed_by_grip_toggle=not args.toggle_grip,
        inertia=args.inertia,
    )

    # Run
    app = WheelApplication(config, edit_mode=args.edit)
    return app.run()


if __name__ == '__main__':
    sys.exit(main())
