#!/usr/bin/env python3
"""
VR Gamepad - Main entry point

Runs the VR controller to virtual gamepad mapper.
Requires SteamVR; connects as an OpenVR Background application.

Usage:
    python vr_gamepad_main.py                    # Run with default mappings
    python vr_gamepad_main.py -c profile.json    # Run with custom profile
    python vr_gamepad_main.py --gui              # Open config GUI
    python vr_gamepad_main.py --monitor          # Open gamepad monitor
    python vr_gamepad_main.py --save-default     # Save default profile
"""

import sys
import time
import signal
import argparse
from pathlib import Path

import _openvr as vr_backend

from _mapping import MappingProfile, create_default_profile
from _mapping_engine import MappingEngine


class Application:
    def __init__(self, profile: MappingProfile):
        self.running = True
        self.profile = profile
        self.engine = None
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        print("\nShutting down...")
        self.running = False
    
    def run(self):
        print("VR Gamepad")
        print("=" * 50)
        print(f"Profile: {self.profile.name}")
        print(f"Mappings: {len(self.profile.mappings)}")
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
        
        # Create mapping engine
        print("Creating virtual gamepad...")
        try:
            self.engine = MappingEngine(self.profile)
        except Exception as e:
            print(f"Error creating virtual gamepad: {e}")
            print()
            print("Make sure you have permissions for /dev/uinput:")
            print("  sudo usermod -aG input $USER")
            print("  sudo modprobe uinput")
            vr_backend.shutdown()
            return 1
        
        print("Virtual gamepad created")
        print()
        
        # Print active mappings
        print("Active mappings:")
        print("-" * 50)
        for m in self.profile.mappings:
            if m.enabled:
                cond = f" [+{len(m.conditions)} conditions]" if m.conditions else ""
                name = f"{m.name}: " if m.name else ""
                print(f"  {name}{m.input_controller}.{m.input_name} -> {m.output_name}{cond}")
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
                    self.engine.update()
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
            if self.engine:
                self.engine.close()
            vr_backend.shutdown()
            print("Done")
        
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="VR Controller to Gamepad mapper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                        Run with default mappings
  %(prog)s -c my_profile.json     Run with custom profile
  %(prog)s --gui                  Open configuration GUI
  %(prog)s --save-default         Save default profile to file

Chord Example:
  In the GUI, create a mapping with conditions. For example:
  - Input: right trigger_click
  - Output: guide button
  - Condition: right grip_click is held
  
  This makes Grip+Trigger on right controller press the Guide button.
        """
    )
    
    parser.add_argument(
        '--config', '-c',
        help='Path to profile JSON file'
    )
    parser.add_argument(
        '--gui',
        action='store_true',
        help='Open configuration GUI'
    )
    parser.add_argument(
        '--monitor',
        action='store_true',
        help='Open gamepad monitor (shows all 32 buttons and 8 axes)'
    )
    parser.add_argument(
        '--save-default',
        metavar='FILE',
        nargs='?',
        const='default_profile.json',
        help='Save default profile to file (default: default_profile.json)'
    )
    parser.add_argument(
        '--list-inputs',
        action='store_true',
        help='List all available VR inputs'
    )
    parser.add_argument(
        '--list-outputs',
        action='store_true',
        help='List all available gamepad outputs'
    )
    
    args = parser.parse_args()
    
    # List inputs
    if args.list_inputs:
        from _mapping import VR_INPUTS
        print("Available VR Inputs:")
        print()
        for controller in ["left", "right"]:
            print(f"  {controller.upper()} CONTROLLER:")
            print(f"    Buttons: {', '.join(VR_INPUTS[controller]['buttons'])}")
            print(f"    Axes: {', '.join(VR_INPUTS[controller]['axes'])}")
            print()
        return 0
    
    # List outputs
    if args.list_outputs:
        from _mapping import GAMEPAD_OUTPUTS
        print("Available Gamepad Outputs:")
        print()
        print(f"  Buttons: {', '.join(GAMEPAD_OUTPUTS['buttons'][:20])}...")
        print(f"           (+ btn_1 through btn_32)")
        print()
        print(f"  Axes: {', '.join(GAMEPAD_OUTPUTS['axes'][:8])}...")
        print(f"        (+ axis_1 through axis_8)")
        return 0
    
    # Save default profile
    if args.save_default:
        profile = create_default_profile()
        profile.save(args.save_default)
        print(f"Saved default profile to: {args.save_default}")
        return 0
    
    # Open GUI
    if args.gui:
        from config_gui import main as gui_main
        gui_main()
        return 0

    # Open monitor
    if args.monitor:
        from monitor_gui import GamepadMonitor
        monitor = GamepadMonitor()
        monitor.run()
        return 0
    
    # Load profile
    if args.config:
        path = Path(args.config)
        if not path.exists():
            print(f"Error: Profile not found: {path}")
            return 1
        try:
            profile = MappingProfile.load(str(path))
        except Exception as e:
            print(f"Error loading profile: {e}")
            return 1
    else:
        profile = create_default_profile()
    
    # Run
    app = Application(profile)
    return app.run()


if __name__ == '__main__':
    sys.exit(main())
