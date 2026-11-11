import argparse, io, queue, socket, threading, tkinter
from dataclasses import dataclass   # needs Python 3.7 or later
from typing import Tuple, Optional

from PIL import Image, ImageTk # on Ubuntu install with "apt install -y python3-pil"

from .lvreceiver import LiveViewReceiver
from .camera import OlympusCamera


##############################################################################
#     class LiveViewWindow displays the camera's live view in a window.      #
##############################################################################

class LiveViewWindow:
    """
    Class *LiveViewWindow* displays the camera's live view in a window.

    :param camera: connection to Olympus camera; instance of class *OlympusCamera*
    :type camera: *OlympusCamera*
    :param port: port to listen to for RTP packages from the camera
    :type port: *int*
    """

    @dataclass
    class CamPropInfo:
        "Information about a camera property."
        name    : str
        "camprop name"
        values  : list
        "values, list of strings"
        cur_val : int
        "current value, index into list of strings"
        variable: tkinter.IntVar
        "variable being watched for changes"

    UPDATE_INTERVAL = 25
    "The queue is checked every this many milliseconds for a new frame."

    def __init__(self, camera: OlympusCamera, port: int = 40000):
        self.power_off = False
        self.camera = camera
        self.port = port
        self.img_queue: queue.SimpleQueue = queue.SimpleQueue()
        self.window = tkinter.Tk()
        self.width = self.height = None
        if 'model' in camera.get_camera_info():
            self.window.title(camera.get_camera_info()['model'])
        else:
            self.window.title("LiveView")

        # Select largest entry in lvqty_list that still fits our screen.
        self.lvqty_list = ['0640x0480']
        if 'switch_cammode' in camera.get_commands():
            args = camera.get_commands()['switch_cammode'].args
            if args is not None and 'mode' in args:
                args1 = args['mode']
                if args1 is not None and 'rec' in args1:
                    args2 = args1['rec']
                    if args2 is not None and 'lvqty' in args2:
                        self.lvqty_list = list(args2['lvqty'])
        self.lvqty_cur = 0
        width_height_min = min(self.window.winfo_screenwidth(),
                               self.window.winfo_screenheight())
        for i, lvqty in enumerate(self.lvqty_list):
            if max([int(c) for c in lvqty.split('x')]) < width_height_min:
                self.lvqty_cur = i
        self.lvqty_var = tkinter.IntVar()
        self.lvqty_var.set(self.lvqty_cur)
        self.lvqty_var.trace_add('write', self.on_lvqty)

        # Collect camera properties for Settings menu.
        self.camprop_info = {}
        camera.send_command('switch_cammode', mode='rec')
        cam_props = camera.xml_query('get_camprop', com='desc',
                                     propname='desclist')
        if isinstance(cam_props, list):
            for prop in cam_props:
                if prop['attribute'] != 'getset':
                    continue
                values = prop['enum'].split()
                index = values.index(prop['value'])
                if index == -1:
                    continue
                variable = tkinter.IntVar()
                variable.set(index)
                variable.trace_add('write', self.on_camprop)
                self.camprop_info[str(variable)] = \
                    self.CamPropInfo(prop['propname'], values, index, variable)
        camera.send_command('switch_cammode', mode='play')

        # Add menu bar.
        self.menubar = tkinter.Menu(self.window)

        # File
        self.filemenu = tkinter.Menu(self.menubar, tearoff=0)
        self.filemenu.add_command(label="Take picture", command=self.take_pic)
        self.filemenu.add_command(label="Set clock", command=self.set_clock)
        self.filemenu.add_command(label="Exit", command=self.window.destroy)
        self.filemenu.add_command(label="Exit & Camera off",
                                  command=self.power_off_and_exit)
        self.menubar.add_cascade(label="File", menu=self.filemenu)

        # View
        self.viewmenu = tkinter.Menu(self.menubar, tearoff=0)
        self.sizemenu = tkinter.Menu(self.viewmenu, tearoff=0)
        for value, label in enumerate(self.lvqty_list):
            self.sizemenu.add_radiobutton(label=label, value=value,
                                          variable=self.lvqty_var)
        self.viewmenu.add_cascade(label="Size", menu=self.sizemenu)
        self.menubar.add_cascade(label="View", menu=self.viewmenu)

        # Settings
        self.campropmenu = tkinter.Menu(self.menubar, tearoff=0)
        for camprop in self.camprop_info.values():
            menu = tkinter.Menu(self.campropmenu, tearoff=0)
            for value, label in enumerate(camprop.values):
                menu.add_radiobutton(label=label, value=value,
                                     variable=camprop.variable)
            self.campropmenu.add_cascade(label=camprop.name, menu=menu)
        self.menubar.add_cascade(label="Settings", menu=self.campropmenu)
        self.window.config(menu=self.menubar)

        # Camera starts broadcasting liveview as RTP packages on given UDP port.
        camera.start_liveview(port=self.port,
                              lvqty=self.lvqty_list[self.lvqty_cur])

        # Start thread that reads liveview, decodes it and queues us jpg images.
        udp_client = LiveViewReceiver(self.img_queue)
        thread = threading.Thread(target=udp_client.receive_packets,
                                  args=[port])
        thread.start()

        # Get first jpeg image.
        self.img = self.next_image()

        # Compute window size from image.
        self.width = self.img.width()
        self.height = self.img.height()
        self.window.geometry(f"{self.width}x{self.height}")
        self.window.configure(background='grey')

        # Make a window with image,
        self.camimage = tkinter.Label(self.window, image=self.img)
        self.camimage.pack(side="bottom", fill="both", expand=1)

        # Show the window and enter main loop.
        self.window.after(self.UPDATE_INTERVAL, self.check_update_image)
        self.window.mainloop()

        # Stop camera broadcasting liveview. When the liveview stops, the
        # read on the UDP socket times out and the thread ends.
        udp_client.shut_down()
        self.camera.stop_liveview()
        thread.join()

        if self.power_off:
            self.camera.send_command('switch_cammode', mode='play')
            self.camera.send_command('exec_pwoff')

    def take_pic(self) -> None:
        "Take a picture."
        self.camera.take_picture()

    def on_lvqty(self, *args) -> None:
        """
        Called when *self.lvqty_var* is written to.

        :param args: ignored
        """
        if self.lvqty_cur != self.lvqty_var.get():
            self.lvqty_cur = self.lvqty_var.get()
            self.camera.stop_liveview()
            self.camera.start_liveview(port=self.port,
                                       lvqty=self.lvqty_list[self.lvqty_cur])

    def on_camprop(self, var_name: str, *dummy) -> None:
        """
        Called when a camprop variable is written to."

        :param var_name: camera property name
        :type var_name: str
        :param dummy: ignored
        """
        camprop = self.camprop_info[var_name]
        if camprop.cur_val != camprop.variable.get():
            camprop.cur_val = camprop.variable.get()
            self.camera.set_camprop(camprop.name,
                                    camprop.values[camprop.cur_val])

    def next_image(self) -> ImageTk.PhotoImage:
        """
        This method returns the next image from the queue.

        :returns: *ImageTk.PhotoImage*
        """
        try:
            jpeg_and_extension = self.img_queue.get(timeout=4.0)
        except queue.Empty as e:
            e.add_note("No data could be fetched within 4s.")
            raise TimeoutError("Timeout while waiting for imagedata from camera. Maybe you need to check your "
                               "firewall settings for incoming UDP traffic (from 192.168.0.10).") from e

        orientation = self.get_orientation(jpeg_and_extension.extension)
        if orientation is None or orientation == 1:
            return ImageTk.PhotoImage(data=jpeg_and_extension.jpeg)
        with io.BytesIO(jpeg_and_extension.jpeg) as file:
            img = Image.open(file)
            img.load()
        img = img.transpose(Image.ROTATE_180 if orientation == 3
                            else Image.ROTATE_90 if orientation == 8
                            else Image.ROTATE_270)
        return ImageTk.PhotoImage(img)

    def check_update_image(self) -> None:
        """
        A timer calls this method periodically. It checks the queue
        for a new image and if there is one updates the window.
        """
        while True:
            if not self.img_queue.empty():
                try:
                    img = self.next_image()
                    self.camimage.configure(image=img)
                    self.img = img
                    if img.width() != self.width or img.height() != self.height:
                        self.width = img.width()
                        self.height = img.height()
                        self.window.geometry(f"{self.width}x{self.height}")
                except OSError:
                    continue
            break
        self.window.after(self.UPDATE_INTERVAL, self.check_update_image)

    def get_orientation(self, extension: bytes) -> Optional[int]:
        """
        Get orientation from RTP extension. Its values are the same as in EXIF:
        1 for 0°, 3 for 180°, 6 for 90° clockwise, and 8 for 270° clockwise.

        :param extension: RTP extension
        :type extension: bytes
        :returns: 1, 3. 6, 8, or *None*.
        """
        idx = 0
        while idx < len(extension):
            func_id = (extension[idx] << 8) + extension[idx+1]
            length  = 4 * ((extension[idx+2] << 8) + extension[idx+3])
            idx += 4

            if func_id == 4: # orientation
                orientation = extension[idx+3]
                return orientation if orientation in [1, 3, 6, 8] else None

            idx += length
        assert idx == len(extension)
        return None

    def set_clock(self):
        """
        Set camera clock.

        The live view is stopped before setting the clock and restarted
        afterwards.
        """
        self.camera.set_clock()

    def power_off_and_exit(self):
        "Turn camera off and exit."
        self.power_off = True
        self.window.destroy()


def main() -> None:
    """
    Main program for script *olympus-liveview*. Parses command-line arguments
    and displays liveview window.
    """
    PORT = 40000

    parser = argparse.ArgumentParser()
    parser.add_argument('--port', '-P', type=int, default=PORT,
                        help=f"UPD port for liveview (default: {PORT}).")
    args = parser.parse_args()

    # Connect to camera.
    camera = OlympusCamera()

    # Report camera model.
    camera.report_model()

    LiveViewWindow(camera, args.port)


if __name__ == '__main__':
    main()

