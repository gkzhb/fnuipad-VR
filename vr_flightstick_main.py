#!/usr/bin/env python3
"""
VR Flight Stick (Stick Yoke) + Throttle - Main entry point

Runs the VR flight stick simulator.
Requires SteamVR; connects as an OpenVR Background application.

Controls:
    Right Controller: Stick yoke
        - Grip to grab the stick
        - Move forward/back for pitch
        - Move left/right for roll
        - Twist for rudder

    Left Controller: Throttle
        - Grip to grab throttle
        - Move up/down for throttle position

Usage:
    python vr_flightstick_main.py                    # Run with default settings
    python vr_flightstick_main.py --deflection 45   # Set max deflection angle
    python vr_flightstick_main.py --edit            # Enter edit mode to position anchors
"""

import sys
import time
import signal
import argparse
from dataclasses import asdict

import _openvr as vr_backend

from _flightstick import (
    FlightStick, FlightStickConfig,
    HONEYCOMB_NAME, HONEYCOMB_VENDOR, HONEYCOMB_PRODUCT,
    TCA_NAME, TCA_VENDOR, TCA_PRODUCT,
    GENERIC_NAME, GENERIC_VENDOR, GENERIC_PRODUCT
)


class FlightStickApplication:
    def __init__(self, config: FlightStickConfig, edit_mode: bool = False):
        self.running = True
        self.config = config
        self.edit_mode = edit_mode
        self.flightstick = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print("\nShutting down...")
        self.running = False

    def run(self):
        print("VR Flight Stick + Throttle")
        print("=" * 50)
        print(f"Device: {self.config.device_name}")
        print(f"VID:PID: {self.config.device_vendor:04x}:{self.config.device_product:04x}")
        print()
        print("Stick Configuration:")
        print(f"  Anchor: {self.config.stick_anchor}")
        print(f"  Length: {self.config.stick_length:.2f}m")
        print(f"  Max deflection: {self.config.max_deflection_degrees}°")
        print(f"  Max twist (rudder): {self.config.max_twist_degrees}°")
        print()
        print("Throttle Configuration:")
        print(f"  Anchor: {self.config.throttle_anchor}")
        print(f"  Range: {self.config.throttle_range:.2f}m")
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

        # Create flight stick
        print("Creating virtual flight stick...")
        try:
            self.flightstick = FlightStick(config=self.config)
        except Exception as e:
            print(f"Error creating flight stick: {e}")
            print()
            print("Make sure you have permissions for /dev/uinput:")
            print("  sudo usermod -aG input $USER")
            print("  sudo modprobe uinput")
            vr_backend.shutdown()
            return 1

        print("Flight stick created")
        print()

        if self.edit_mode:
            print("EDIT MODE")
            print("-" * 50)
            print("Right trigger - Set stick anchor position")
            print("Left trigger - Set throttle anchor position")
            print("Press Ctrl+C when done")
            print("-" * 50)
        else:
            print("Controls:")
            print("-" * 50)
            print("  RIGHT CONTROLLER (Stick Yoke):")
            print("    Grip - Grab the stick")
            print("    Forward/Back - Pitch (elevator)")
            print("    Left/Right - Roll (ailerons)")
            print("    Twist - Rudder (yaw)")
            print()
            print("  LEFT CONTROLLER (Throttle):")
            print("    Grip - Grab throttle")
            print("    Up/Down - Throttle position")
            print("-" * 50)
            print()
            print("Axis Mapping:")
            print("  Pitch -> Right Stick Y")
            print("  Roll  -> Right Stick X")
            print("  Rudder -> Left Stick X")
            print("  Throttle -> Left Trigger")

        print()
        print("Running... Press Ctrl+C to stop")
        print()

        # Target ~90Hz
        frame_time = 1.0 / 90.0

        # For periodic status display
        last_status_time = 0
        status_interval = 1.0  # Print status every second

        try:
            while self.running:
                start = time.perf_counter()

                try:
                    if self.edit_mode:
                        self.flightstick.edit_mode()
                    else:
                        self.flightstick.update()

                        # Print status periodically
                        current_time = time.perf_counter()
                        if current_time - last_status_time >= status_interval:
                            axes = self.flightstick.get_axis_values()
                            print(f"\rPitch: {axes['pitch']:+.2f} | "
                                  f"Roll: {axes['roll']:+.2f} | "
                                  f"Rudder: {axes['rudder']:+.2f} | "
                                  f"Throttle: {axes['throttle']:.2f} | "
                                  f"Stick: {'HELD' if axes['stick_grabbed'] else 'free'} | "
                                  f"Throttle: {'HELD' if axes['throttle_grabbed'] else 'free'}",
                                  end='', flush=True)
                            last_status_time = current_time

                except vr_backend.SessionEnded as e:
                    print(e)
                    return 0
                except vr_backend.OpenVRError as e:
                    print(f"\nOpenVR error: {e}")
                    return 1

                elapsed = time.perf_counter() - start
                sleep_time = frame_time - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        finally:
            print("\nCleaning up...")
            if self.flightstick:
                # Print final config if in edit mode
                if self.edit_mode:
                    print()
                    print("Final configuration:")
                    print(f"  stick_anchor: {self.config.stick_anchor}")
                    print(f"  throttle_anchor: {self.config.throttle_anchor}")
                self.flightstick.close()
            vr_backend.shutdown()
            print("Done")

        return 0


def main():
    parser = argparse.ArgumentParser(
        description="VR Flight Stick + Throttle Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              Run with default settings
  %(prog)s --deflection 45              Set max deflection to 45 degrees
  %(prog)s --twist 60                   Set max rudder twist to 60 degrees
  %(prog)s --edit                       Position the stick and throttle in VR
  %(prog)s --warthog                    Emulate Thrustmaster HOTAS Warthog

Axis Mapping:
  By default, axes are mapped as:
    Pitch  -> Right Stick Y (elevator)
    Roll   -> Right Stick X (ailerons)
    Rudder -> Left Stick X (yaw)
    Throttle -> Left Trigger

  Use --invert-* flags to invert specific axes.

Positioning:
  Use --edit mode to position the stick and throttle anchors in VR.
  Right trigger sets stick anchor, left trigger sets throttle anchor.
        """
    )

    # Stick settings
    parser.add_argument(
        '--stick-anchor',
        type=float,
        nargs=3,
        metavar=('X', 'Y', 'Z'),
        default=[0.0, -1.2, -0.35],
        help='Stick BASE position (default: 0.0 -1.2 -0.35, grip at knee height)'
    )
    parser.add_argument(
        '--stick-length',
        type=float,
        default=0.7,
        help='Virtual stick length in meters (default: 0.7, classic yoke)'
    )
    parser.add_argument(
        '--deflection',
        type=float,
        default=15.0,
        help='Max deflection angle in degrees (default: 15, lower = tighter)'
    )
    parser.add_argument(
        '--twist',
        type=float,
        default=45.0,
        help='Max twist angle for rudder in degrees (default: 45)'
    )

    # Throttle settings
    parser.add_argument(
        '--throttle-anchor',
        type=float,
        nargs=3,
        metavar=('X', 'Y', 'Z'),
        default=[-0.3, -0.4, -0.3],
        help='Throttle anchor position (default: -0.3 -0.4 -0.3)'
    )
    parser.add_argument(
        '--throttle-range',
        type=float,
        default=0.3,
        help='Throttle movement range in meters (default: 0.3)'
    )

    # Sensitivity
    parser.add_argument(
        '--pitch-sensitivity',
        type=float,
        default=1.0,
        help='Pitch sensitivity multiplier (default: 1.0)'
    )
    parser.add_argument(
        '--roll-sensitivity',
        type=float,
        default=1.0,
        help='Roll sensitivity multiplier (default: 1.0)'
    )
    parser.add_argument(
        '--rudder-sensitivity',
        type=float,
        default=1.0,
        help='Rudder sensitivity multiplier (default: 1.0)'
    )

    # Deadzone
    parser.add_argument(
        '--stick-deadzone',
        type=float,
        default=0.05,
        help='Stick deadzone (0-1, default: 0.05)'
    )
    parser.add_argument(
        '--rudder-deadzone',
        type=float,
        default=0.08,
        help='Rudder deadzone (0-1, default: 0.08)'
    )
    parser.add_argument(
        '--throttle-deadzone',
        type=float,
        default=0.02,
        help='Throttle deadzone (0-1, default: 0.02)'
    )

    # Inversion
    parser.add_argument(
        '--invert-pitch',
        action='store_true',
        help='Invert pitch axis'
    )
    parser.add_argument(
        '--invert-roll',
        action='store_true',
        help='Invert roll axis'
    )
    parser.add_argument(
        '--invert-rudder',
        action='store_true',
        help='Invert rudder axis'
    )

    # Center lerp
    parser.add_argument(
        '--center-lerp',
        type=float,
        default=3.0,
        help='Stick center lerp speed (0 = no centering, default: 3.0)'
    )

    # Grab radius
    parser.add_argument(
        '--grab-radius',
        type=float,
        default=0.15,
        help='How close to stick grip to grab (meters, default: 0.15)'
    )
    parser.add_argument(
        '--throttle-grab-radius',
        type=float,
        default=0.12,
        help='How close to throttle to grab (meters, default: 0.12)'
    )

    # Display options
    parser.add_argument(
        '--no-stick',
        action='store_true',
        help='Hide stick overlay'
    )
    parser.add_argument(
        '--no-throttle',
        action='store_true',
        help='Hide throttle overlay'
    )

    # Grip mode
    parser.add_argument(
        '--toggle-grip',
        action='store_true',
        help='Toggle grip on/off (instead of hold)'
    )

    # Device identity
    parser.add_argument(
        '--tca',
        action='store_true',
        help='Emulate Thrustmaster TCA Yoke Boeing'
    )
    parser.add_argument(
        '--generic',
        action='store_true',
        help='Use generic device identity'
    )

    # Special modes
    parser.add_argument(
        '--edit',
        action='store_true',
        help='Enter edit mode to position anchors'
    )

    args = parser.parse_args()

    # Build config - default to Honeycomb Alpha (widely recognized)
    if args.tca:
        device_name = TCA_NAME
        device_vendor = TCA_VENDOR
        device_product = TCA_PRODUCT
    elif args.generic:
        device_name = GENERIC_NAME
        device_vendor = GENERIC_VENDOR
        device_product = GENERIC_PRODUCT
    else:
        device_name = HONEYCOMB_NAME
        device_vendor = HONEYCOMB_VENDOR
        device_product = HONEYCOMB_PRODUCT

    config = FlightStickConfig(
        stick_anchor=tuple(args.stick_anchor),
        stick_length=args.stick_length,
        max_deflection_degrees=args.deflection,
        max_twist_degrees=args.twist,
        stick_deadzone=args.stick_deadzone,
        rudder_deadzone=args.rudder_deadzone,
        pitch_sensitivity=args.pitch_sensitivity,
        roll_sensitivity=args.roll_sensitivity,
        rudder_sensitivity=args.rudder_sensitivity,
        invert_pitch=args.invert_pitch,
        invert_roll=args.invert_roll,
        invert_rudder=args.invert_rudder,
        throttle_anchor=tuple(args.throttle_anchor),
        throttle_range=args.throttle_range,
        throttle_deadzone=args.throttle_deadzone,
        stick_center_lerp=args.center_lerp,
        stick_grab_radius=args.grab_radius,
        throttle_grab_radius=args.throttle_grab_radius,
        show_stick=not args.no_stick,
        show_throttle=not args.no_throttle,
        stick_grabbed_by_grip=True,
        stick_grabbed_by_grip_toggle=not args.toggle_grip,
        throttle_grabbed_by_grip=True,
        throttle_grabbed_by_grip_toggle=not args.toggle_grip,
        device_name=device_name,
        device_vendor=device_vendor,
        device_product=device_product,
    )

    # Run
    app = FlightStickApplication(config, edit_mode=args.edit)
    return app.run()


if __name__ == '__main__':
    sys.exit(main())
