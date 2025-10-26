import argparse, datetime, os, sys
from .camera import OlympusCamera


##############################################################################
#    Function download_photos() downloads photos from the Olympus camera.    #
##############################################################################


def download_photos(
    camera: OlympusCamera,
    output_dir: str,
    daterange: tuple = (None, None)
) -> None:
    """
    Function download_photos() downloads photos from the Olympus camera.

    :param output_dir: local directory to write downloaded camera images to
    :type output_dir: *str*
    :param daterange: Optional - a tuple (start, end) of datetime objects
        designating the time range to download images from
    :returns: nothing; warnings are written to *stdout*
    """
    for cam_file in camera.list_images():
        # Check if user specified a daterange
        if all(daterange):

            # If cam_file.date_time lies outside specified range, skip
            file_date = datetime.datetime.fromisoformat(
                cam_file.date_time
            )

            if not (daterange[0] <= file_date <= daterange[1]):
                continue

        local_dir = os.path.join(os.path.expanduser('~'), 'Pictures',
                                 cam_file.date_time[:4]) if output_dir is None\
                                                         else output_dir

        # Create output directory if it does not exist.
        if not os.path.exists(local_dir):
            try:
                os.makedirs(local_dir)
            except Exception as e:
                print(f"Cannot create directory '{local_dir}': {str(e)}.")
                break

        # Local filename to open and write to.
        local_file = os.path.join(local_dir, cam_file.file_name.split('/')[-1])

        # Local filename used in in messages.
        msg_file = local_file.replace(os.path.expanduser('~'), '~')

        # Turn time into datetime object.
        dt = datetime.datetime.strptime(cam_file.date_time, '%Y-%m-%dT%H:%M:%S')

        # Time in seconds since epoch.
        tim_epoch = dt.timestamp()

        # Skip image download if local file already exists.
        if os.path.exists(local_file):
            stat = os.stat(local_file)
            if stat.st_size == cam_file.file_size and \
                   abs(tim_epoch - stat.st_mtime) < 10:
                print(f"File '{msg_file}' exists; skipping download.")
            elif stat.st_size != cam_file.file_size:
                print(f"File '{msg_file}' exists and size differs; "
                      "skipping download.")
            else:
                print(f"File '{msg_file}' exists and modification time differs;"
                      " skipping download.")
            continue

        # Download image.
        image = camera.download_image(cam_file.file_name)
        if image is not None:
            assert len(image) == cam_file.file_size

            # Write image to local file.
            try:
                with open(local_file, 'wb') as f:
                    f.write(image)
            except Exception as e:
                print(f"Failed to download '{cam_file.file_name}' to "
                      f"'{msg_file}': {str(e)}.")
                try:
                    os.remove(local_file)
                except:
                    pass
                continue

            print(f"File '{cam_file.file_name}' of {cam_file.file_size:,} bytes"
                  f" from {dt} downloaded to '{msg_file}'.")

            # Set local file's creation and modification time.
            os.utime(local_file, (tim_epoch, tim_epoch))

def main() -> None:
    """
    Main program for script *olympus-download*. Parses command-line arguments
    and calls APIs.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', required=False, default=None,
                        help="Local directory for downloaded photos.")
    parser.add_argument('--date-range', '-D',
                        nargs=2, type=parse_date, metavar=('START', 'END'),
                        default=(None, None),
                        help='Start and end dates to download photos from. '
                             'Must be in YYYY-MM-DD format. If argument not '
                             'given, will download everything.')
    parser.add_argument('--power_off', '-p', action="store_true",
                        required=False, help="Turn camera off.")
    parser.add_argument('--set_clock', '-c', action="store_true",
                        help="Set camera clock to current time.")

    args = parser.parse_args()
    if all(args.date_range):
        start, end = args.date_range
        if start > end:
            parser.error(
                "Start date must be before end date"
            )

    # Connect to camera.
    camera = OlympusCamera()

    # Report camera model.
    camera.report_model()

    # Set camera's clock if requested.
    if args.set_clock:
        camera.set_clock()

    download_photos(camera, args.output, args.date_range)

    # Turn camera off if requested.
    if args.power_off:
        camera.send_command('exec_pwoff')


def parse_date(date_string: str) -> datetime.datetime:
    """
    Parses date string into a datetime object
    """
    try:
        return datetime.datetime.strptime(
            date_string,
            '%Y-%m-%d',
        )

    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date format: {date_string}. \n"
            f"Please use YYYY-MM-DD"
        )


if __name__ == '__main__':
    main()
