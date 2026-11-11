import queue, socket
from dataclasses import dataclass   # needs Python 3.7 or later
from typing import Tuple


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
