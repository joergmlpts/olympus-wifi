import argparse, io, queue, socket, threading, tkinter
from dataclasses import dataclass   # needs Python 3.7 or later
from typing import Tuple, Optional

from PIL import Image, ImageTk # on Ubuntu install with "apt install -y python3-pil"

from .camera import OlympusCamera


###########################################################################
# class LiveViewReceiver receives the camera's live view and enters it as #
# sequence of jpeg images in a queue.                                     #
###########################################################################

class LiveViewReceiver:
    """
    Class *LiveViewReceiver* receives the camera's live view and appends
    it as sequence of JPEG images to a queue.

    :param img_queue: instances of *JPEGandExtension* are appended to this queue
    :type img_queue: *queue.SimpleQueue*
    """

    @dataclass
    class JPEGandExtension:
        """
        This class stores a JPEG image and and RTP extension. Instances of
        this class are appended to the queue. 
        """
        jpeg     : bytes
        "JPEG image"
        extension: bytes
        "RTP extension"

    JPEG_START     = b'\xff\xd8'
    "JPEG images start with this magic number"
    JPEG_END       = b'\xff\xd9'
    "JPEG images end with this magic number"
    MAX_QUEUE_SIZE = 50
    "The queue will not contain more than this many entries"

    # A queue is passed, JEPG images will be added to this queue.
    def __init__(self, img_queue: queue.SimpleQueue):
        self.running = True
        self.img_queue = img_queue
        self.prev_sequence_number = 0
        self.init_frame(valid=False)

    def shut_down(self):
        "Request showdown of this *LiveViewReceiver* thread."
        self.running = False

    def receive_packets(self, port: int) -> None:
        """
        This main loop receives RTP packets from the camera. It runs in
        a thread in parallel to the gui.

        :param port: port to listen to for RTP packages from the camera
        :type port: int
        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("", port))
            sock.settimeout(1) # A timeout terminates the loop below.
            while True:
                # read packet from socket
                try:
                    packet = sock.recv(4096)
                except Exception as e:
                    if 'timed out' in str(e):
                        if self.running:
                            # Not yet shutting down, keep going.
                            continue
                    else:
                        print("Error reading liveview:", str(e))
                    break
                self.process_packet(packet)

    def decode_RTP(self, packet: bytes) -> Tuple[int, int, bytes]:
        """
        Decodes an RTP packet stores extension in *self.extension* and extracts
        marker, sequence number, and payload.

        Based on: https://en.wikipedia.org/wiki/Real-time_Transport_Protocol

        :param packet: packet received from camera consisting of JPEG image and RTP entension
        :type packet: *bytes*
        :returns: triple consisting of *marker*, *sequence_number*, and *payload*
        """
        version = packet[0] >> 6
        assert version == 2

        padding = bool(packet[0] & 32)
        extension = bool(packet[0] & 16)
        CSRC_count = packet[0] & 15
        marker = bool(packet[1] & 128)
        sequence_number = (packet[2] << 8) + packet[3]
        '''
        payload_type = packet[1] & 127
        time_stamp = (packet[4] << 24) + (packet[5] << 16) + \
                     (packet[6] << 8) + packet[7]
        SSRC_identifier = (packet[8] << 24) + (packet[9] << 16) + \
                          (packet[10] << 8) + packet[11]
        '''

        # Remove padding if needed.
        if padding:
            packet = packet[:-packet[-1]]

        # Extract payload, save extension.
        if extension:
            start = 14+4*CSRC_count
            extension_header_length = (packet[start] << 8) + packet[start+1]
            start += 2
            size = 4*extension_header_length
            self.extension = packet[start:start+size]
            payload = packet[start+size:]
        else:
            payload = packet[12+4*CSRC_count:]

        return marker, sequence_number, payload

    def init_frame(self, valid: bool=True) -> None:
        """
        Start a frame; called when marker bit seen.

        :param valid: is frame valid; frames are valid when they have the expected sequence number
        :type valid: bool
        """
        self.assembling_frame = valid
        self.frame = b''
        self.extension = b''

    def process_packet(self, packet: bytes) -> None:
        """
        Assembles multiple packets into one frame. Calls *process_frame* with
        each frame.

        Based on: https://stackoverflow.com/questions/7665217 where we are
        dealing here with MJPEG, not H264.

        :param packet: packet received from camera consisting of JPEG image and RTP entension
        :type packet: *bytes*
        """
        # Extract payload, marker, and sequence number.
        marker, sequence_number, payload = self.decode_RTP(packet)

        # Assemble payloads into frames.
        if self.assembling_frame:
            self.frame += payload
            if (self.prev_sequence_number + 1) % 65536 != sequence_number:
                # Invalidate frame due to out of sequence packet.
                self.init_frame(valid=False)
        self.prev_sequence_number = sequence_number
        if marker:
            if self.frame:
                self.process_frame(self.frame)
            self.init_frame()

    def process_frame(self, frame: bytes) -> None:
        """
        Appends frame - a JEPG image - and extension from *self.extension*
        to queue.

        :param frame: frame received from camera
        :type frame: *bytes*
        """
        if frame[:2] == self.JPEG_START and frame[-2:] == self.JPEG_END:
            while self.img_queue.qsize() >= self.MAX_QUEUE_SIZE:
                # Take oldest frame from queue to make room.
                self.img_queue.get()
            self.img_queue.put(self.JPEGandExtension(frame, self.extension))


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

