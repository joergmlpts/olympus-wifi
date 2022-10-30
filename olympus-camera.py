#!/usr/bin/env python3

import sys

from camera import OlympusCamera, RequestError, ResultError
from liveview import LiveViewWindow
from download import download_photos

from typing import Dict, Optional

######################################################################
# Send user-supplied command to camera, supports output redirection. #
######################################################################

# Returns True on error.
def user_command(camera: OlympusCamera, cmd: str) -> bool:

    # Parse command.
    cmd_list = cmd.strip().split(' ')

    if len(cmd_list) == 0:
        print(f"Error in '{cmd}': no command found.", file=sys.stderr)
        return True

    command = cmd_list[0]         # command to send to camera
    args: Dict[str, str] = {}     # key-value arguments
    outfile: Optional[str] = None # file name for output redirection
    append: bool = False          # write or append to redirected output

    idx = 1
    while idx < len(cmd_list):
        key_val = cmd_list[idx].strip()

        if not key_val:
            continue

        # parse redirection
        if key_val[0] == '>':
            if len(key_val) > 1:
                if key_val[1] == '>':
                    append = True
                    key_val = key_val[2:]
            if not append:
                key_val = key_val[1:]
            if len(key_val) > 1:
                outfile = key_val.strip()
                idx += 1
                continue
            if idx < len(cmd_list) - 1:
                outfile = cmd_list[idx+1].strip()
                idx += 2
                continue
            else:
                print(f"Error in '{cmd}': redirection file missing.",
                      file=sys.stderr)
                return True

        # parse key-value pair
        eq_idx = key_val.find('=')

        if eq_idx > 0:
            key = key_val[:eq_idx].strip()
            val = key_val[eq_idx+1:].strip()

        if eq_idx <= 0 or not key or not val:
            print(f"Error in '{cmd}': parameter '{key_val}' is not of "
                  "format key=value.", file=sys.stderr)
            return True

        if key in args:
            print(f"Error in '{cmd}': duplicate '{key}'.", file=sys.stderr)
            return True

        args[key] = val
        idx += 1

    # Send command to camera.
    try:

        response = camera.send_command(command, **args)

    except RequestError as e:
        print(e, file=sys.stderr)
        return True

    except ResultError as e:
        print(e, file=sys.stderr)
        return True

    # Redirect result to file or print it.
    if outfile:
        try:
            with open(outfile, 'ab' if append else 'wb') as file:
                file.write(response.content)
        except Exception as e:
            print(f"Error writing to file '{outfile}': {str(e)}.",
                  file=sys.stderr)
            return True
    elif 'Content-Type' in response.headers and \
         response.headers['Content-Type'].startswith('text'):
        # Response is text; print to console.
        print(response.text)
    elif response.content:
        # Response is binary data; suggest redirection, do not print.
        l = len(response.content)
        content = response.headers['Content-Type'] \
                  if 'Content-Type' in response.headers \
                  else 'unknown kind'
        print(f"Command '{cmd}' returned {l:,} bytes of {content}. "
              "Re-run with redirection to obtain data.")
    return False


#################################
# Command-line argument parser. #
#################################

if __name__ == '__main__':
    import argparse

    PORT = 40000

    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', required=False, default=None,
                        help="Local directory for downloaded photos.")
    parser.add_argument('--download', '-d', action="store_true",
                        required=False, help="Download photos from camera.")
    parser.add_argument('--power_off', '-p', action="store_true",
                        required=False, help="Turn camera off.")
    parser.add_argument('--set_clock', '-c', action="store_true",
                        help="Set camera clock to current time.")
    parser.add_argument('--shoot', '-S', action="store_true",
                        help="Take a picture.")
    parser.add_argument('--liveview', '-L', action="store_true",
                        required=False, help="Show live camera stream. Close "
                        "the live view window to quit. This script will run a "
                        "few more seconds, then exit.")
    parser.add_argument('--port', '-P', type=int, default=PORT,
                        help=f"UPD port for liveview (default: {PORT}).")
    parser.add_argument('--cmd', '-C', type=str, nargs='+', help="Command to "
                        "send to camera; multiple commands are supported.")

    args = parser.parse_args()

    # Connect to camera.
    camera = OlympusCamera()

    # Report camera model.
    camera.report_model()

    # Set camera's clock if requested.
    if args.set_clock:
        camera.set_clock()

    if args.cmd:
        for cmd in args.cmd:
            if user_command(camera, cmd):
                break

    if args.shoot:
        camera.take_picture()

    if args.liveview:
        LiveViewWindow(camera, args.port)

    if args.download:
        download_photos(camera, args.output)

    # Turn camera off if requested.
    if args.power_off:
        camera.send_command('exec_pwoff')
