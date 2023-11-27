import datetime, os, sys, time

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass   # needs Python 3.7 or later
from typing import List, Dict, Optional, Set, Union

import requests # on Ubuntu install with "apt install -y python3-requests"


###############################################################################
#                               Exceptions                                    #
###############################################################################

class RequestError(Exception):
    """
    Exception for error in camera command request.

    :param msg: error message
    :type msg: *str*
    """
    def __init__(self, msg: str):
        super().__init__(msg)

class ResultError(Exception):
    """
    Exception for error returned by camera.

    :param msg: error message
    :type msg: *str*
    :param response: *requests* response object
    :type response: *requests.Response*
    """
    def __init__(self, msg: str, response: requests.Response):
        super().__init__(msg)
        self.response = response


###############################################################################
# Class OlympusCamera communicates with an Olympus camera via wifi. It needs  #
# to run on a computer that is connected to the camera's wifi network.        #
###############################################################################

class OlympusCamera:
    """
    Class *OlympusCamera* communicates with an Olympus camera via wifi. It needs
    to run on a computer that is connected to the camera's wifi network.

    The communication via wifi with an Olympus camera is described here:
    `OPC Communication Protocol 1.0a <https://raw.githubusercontent.com/ccrome/olympus-omd-remote-control/master/OPC_Communication_Protocol_EN_1.0a/OPC_Communication_Protocol_EN_1.0a.pdf>`_

    Camera commands vary from camera model to camera model. The camera is
    queried for its list of supported commands and their arguments.
    """

    @dataclass
    class CmdDescr:
        "Description of a single camera command."
        method: str
        "HTTP-method *get* or *post*"
        args  : Dict[str, Optional[dict]]
        "nested dicts of command's key-value argument pairs"

    @dataclass
    class FileDescr:
        "This class describes an image file available for download."
        file_name: str
        "example '/DCIM/100OLYMP/P1010042.JPG'"
        file_size: int
        "in bytes"
        date_time: str
        "ISO date and time, no timezone"

    URL_PREFIX          = "http://192.168.0.10/"
    """
    This is the camera's URL when the computer is connected to
    the camera's wifi.
    """
    HEADERS             = { 'Host'      : '192.168.0.10',
                            'User-Agent': 'OI.Share v2' }
    """
    Headers to send when communicating with camera.
    """

    ANY_PARAMETER                               = '*'
    EMPTY_PARAMETERS: Dict[str, Optional[dict]] = { ANY_PARAMETER: None }

    def __init__(self):
        self.versions: Dict[str, str] = {}  # version data
        self.supported: Set[str] = set()    # supported functionality
        self.camera_info = None             # includes camera model
        self.commands: Dict[str, CmdDescr] = {
            'get_commandlist': self.CmdDescr('get', None)
        }

        response = self.send_command('get_commandlist')
        if response is None:
            return

        # Parse XML command description and populate members
        # self.versions, self.supported, and self.commands.
        for elem in ElementTree.fromstring(response.text):
            if elem.tag == 'cgi':
                for http_method in elem:
                    if http_method.tag == 'http_method':
                        self.commands[elem.attrib['name']] = \
                            self.CmdDescr(http_method.attrib['type'],
                                          self.commandlist_cmds(http_method))
            elif elem.tag == 'support':
                self. supported.add(elem.attrib['func'])
            elif 'version' in elem.tag:
                self.versions[elem.tag] = elem.text.strip()

        # Issue get-camera-info command. It returns the camera model.
        self.camera_info = self.xml_query('get_caminfo')

        # Get lists of supported values for writable camera properties.
        self.send_command('switch_cammode', mode='rec')
        self.camprop_name2values = {
            prop['propname'] : prop['enum'].split() for prop in
            self.xml_query('get_camprop', com='desc', propname='desclist')
            if prop['attribute'] == 'getset' and 'enum' in prop
        }

        # Switch to mode 'play'.
        self.send_command('switch_cammode', mode='play')

    def commandlist_params(self, parent: ElementTree.Element) \
                                                   -> Dict[str, Optional[dict]]:
        "Parse parameters in the XML output of command get_commandlist."
        params = {}
        for param in parent:
            if param.tag.startswith('cmd'):
                return { self.ANY_PARAMETER: { param.attrib['name'].strip():
                                                 self.commandlist_params(param)
                                             }
                       }
            else:
                name = param.attrib['name'].strip() if 'name' in param.attrib \
                                                    else self.ANY_PARAMETER
                params[name] = self.commandlist_cmds(param)
        return params if len(params) else self.EMPTY_PARAMETERS

    def commandlist_cmds(self, parent: ElementTree.Element) \
                                         -> Optional[Dict[str, Optional[dict]]]:
        "Parse commands in the XML output of command get_commandlist."
        cmds: Dict[str, Optional[dict]] = {}
        for cmd in parent:
            assert cmd.tag.startswith('cmd')
            cmds[cmd.attrib['name'].strip()] = self.commandlist_params(cmd)
        return cmds if cmds else None

    def send_command(self, command: str, **args) -> requests.Response:
        """
        Send command to camera; return *Response* object or *None*.

        :param command: camera command
        :type command: *str*
        :param args: dict of command arguments
        :type args: *Dict[str,CmdDescr]*
        """
        # Check command and args against what the camera supports.
        self.check_valid_command(command, args)

        url = f'{self.URL_PREFIX}{command}.cgi'
        if self.commands[command].method == 'get':
            response = requests.get(url, headers=self.HEADERS, params=args)
        else:
            assert self.commands[command].method == 'post'
            if 'post_data' in args:
                post_data = args['post_data']
                del args['post_data']
            else:
                raise RequestError(f"Error in '{command}' with args "
                          f"'{', '.join([k+'='+v for k, v in args.items()])}': "
                          "missing entry 'post_data' for method 'post'.")
            headers = self.HEADERS.copy()
            if len(post_data) > 6 and post_data[:6] == "<?xml ".encode('utf-8'):
                headers['Content-Type'] = 'text/plain;charset=utf-8'
            response = requests.post(url, headers=headers, params=args,
                                     data=post_data)

        if response.status_code in [requests.codes.ok, requests.codes.accepted]:
            return response
        else:
            err_xml = self.xml_response(response)
            if isinstance(err_xml, dict):
                msg = ', '.join([f'{key}={value}'
                                 for key, value in err_xml.items()])
            else:
                msg = response.text.replace('\r\n','')
            raise ResultError(f"Error #{response.status_code} "
                              f"for url '{response.url.replace('%2F','/')}': "
                              f"{msg}.", response)

    # Check validity of command and arguments.
    def check_valid_command(self, command: str,
                            args: Dict[str, CmdDescr]) -> None:
        """
        Check validity of command and arguments.

        :param command: camera command
        :type command: *str*
        :param args: dict of command arguments
        :type args: *Dict[str, CmdDescr]*
        :raises: raises *RequestError* if not a valid camera command
        """

        # Check command.
        if command not in self.commands:
            raise RequestError(f"Error: command '{command}' not supported; "
                               "valid commands: "
                               f"{', '.join(list(self.commands))}.")

        valid_command_arguments = self.commands[command].args

        # Check command arguments.
        wildcard = self.ANY_PARAMETER
        for key, value in args.items():

            if key == 'post_data' and self.commands[command].method == 'post':
                if not isinstance(value, bytes):
                    raise RequestError(f"Error in {command}: data for method "
                                       f"'post' is of type '{type(value)}'; "
                                       "type 'bytes' expected.")
                continue

            # No (more) valid arguments?
            if valid_command_arguments is None:
                raise RequestError(f"Error in {command}: '{key}' in "
                                   f"{key}={value} not supported.")

            # Is key a valid argument?
            if key in valid_command_arguments:
                valid_command_arguments = valid_command_arguments[key]
            elif wildcard in valid_command_arguments:
                valid_command_arguments = valid_command_arguments[wildcard]
            else:
                raise RequestError(f"Error in {command}: '{key}' in "
                                   f"{key}={value} not supported; supported: "
                                 f"{', '.join(list(valid_command_arguments))}.")

            # Is value valid for key?
            if value in valid_command_arguments:
                valid_command_arguments = valid_command_arguments[value]
            elif wildcard in valid_command_arguments:
                valid_command_arguments = valid_command_arguments[wildcard]
            else:
                raise RequestError(f"Error in {command}: '{value}' in "
                                   f"{key}={value} not supported; supported: "
                  f"{', '.join([key+'='+v for v in valid_command_arguments])}.")

    def get_versions(self) -> Dict[str, str]:
        """
        Return a dict with version info; obtained from the camera
        with command 'get_commandlist'.
        """
        return self.versions

    def get_supported(self) -> Set[str]:
        """
        Return a set of supported funcs; obtained from the camera
        with command 'get_commandlist'.
        """
        return self.supported

    def get_camera_info(self) -> Dict[str, str]:
        """
        Return a dict with an entry for 'model', the camera model.
        """
        return self.camera_info

    def get_commands(self) -> Dict[str, CmdDescr]:
        """
        Return dict of permitted commands. Each command maps to an instance
        of class *CmdDescr* which holds the HTTP-method ('get' or 'post') and
        nested dicts that represent supported command arguments and their
        values; obtained from the camera with command 'get_commandlist'.
        """
        return self.commands

    def get_settable_propnames_and_values(self) -> Dict[str, List[str]]:
        """
        Return dict of camera properties and list of their supported values.
        """
        return self.camprop_name2values

    def get_camprop(self, propname: str) -> str:
        """
        Get the value of camera property. A dict of all supported property
        names can be obtained with:

        get_commands()['get_camprop'].args['com']['get']['propname']

        :param propname: supported property name
        :type propname: *str*
        :raises: raises *RequestError* if not a valid camera property
        :returns: value of *propname*
        """
        self.send_command('switch_cammode', mode='rec')
        result = self.xml_query('get_camprop', com='get',
                                propname=propname)
        assert isinstance(result, dict) and 'value' in result
        return result['value']

    def set_camprop(self, propname: str, value: str) -> None:
        """
        Set the value of camera property. A dict of all supported property
        names can be obtained with:

        get_settable_propnames_and_values()

        The list of supported values for property propname can be obtained with:

        get_settable_propnames_and_values()[propname]

        :param propname: supported property name
        :type propname: *str*
        :param value: value for *propname*
        :type value: *str*
        :raises: raises *RequestError* if not a valid camera property or value
        """
        if propname in self.camprop_name2values and \
           value not in self.camprop_name2values[propname]:
            all_values = ', '.join([v for v in
                                    self.camprop_name2values[propname]])
            raise RequestError(f"Error: value '{value}' not supported for "
                               f"camera property '{propname}'; supported "
                               f"values: {all_values}.")
        self.send_command('switch_cammode', mode='rec')
        set_value_xml = '<?xml version="1.0"?>\r\n<set>\r\n' \
                       f'<value>{value}</value>\r\n</set>\r\n'
        self.send_command('set_camprop', com='set', propname=propname,
                          post_data=set_value_xml.encode('utf-8'))

    def xml_response(self, response: requests.Response) -> \
                          Optional[Union[Dict[str, str], List[Dict[str, str]]]]:
        """
        Turn an XML response into a dict or a list of dicts.

        :param response: *requests* response object
        :type response: *requests.Response*
        :returns: *Dict[str,str]*, *List[Dict[str,str]]*, or *None*
        """
        if 'Content-Type' in response.headers and \
           response.headers['Content-Type'] == 'text/xml':
            xml = ElementTree.fromstring(response.text)
            my_dict: Dict[str, str] = {}
            my_list: List[Dict[str, str]] = self.xml2dict(xml, my_dict)
            if not my_list:
                return my_dict
            return my_list[0] if len(my_list) == 1 else my_list
        return None

    def xml2dict(self, xml: ElementTree.Element,
                 parent: Dict[str, str])  -> List[Dict[str, str]]:
        """
        Recursively traverse XML and return a list of dicts.

        :param xml: XML element
        :type xml: * ElementTree.Element*
        :param parent: parent directory
        :type parent: *Dict[str, str]*
        :returns: *Dict[str,str]*, *List[Dict[str,str]]*, or *None*
        """
        if xml.text and xml.text.strip():
            parent[xml.tag] = xml.text.strip()
            return []
        else:
            results = []
            params: Dict[str, str] = {}
            for elem in xml:
                results += self.xml2dict(elem, params)
            if params:
                results.append(params)
            return results

    def xml_query(self, command: str, **args) -> \
                          Optional[Union[Dict[str, str], List[Dict[str, str]]]]:
        """
        Send a command and return XML response as dict or list of dicts.

        :param command: camera command
        :type command: *str*
        :param args: dict of command arguments
        :type args: *Dict[str,CmdDescr]*
        :returns: *Dict[str,str]*, *List[Dict[str,str]]*, or *None*
        """
        return self.xml_response(self.send_command(command, **args))

    def set_clock(self) -> None:
        """
        Set the camera clock to this computer's time.
        """
        self.send_command('switch_cammode', mode='play')
        self.send_command('set_utctimediff', utctime=
                          datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S"),
                          diff=time.strftime("%z"))

    def take_picture(self) -> None:
        """
        The camera takes a picture.
        """
        self.send_command('switch_cammode', mode='shutter')
        time.sleep(0.5)
        self.send_command('exec_shutter', com='1st2ndpush')
        time.sleep(0.5)
        self.send_command('exec_shutter', com='2nd1strelease')
        self.send_command('switch_cammode', mode='play')

    def list_images(self, dir: str = '/DCIM') -> List[FileDescr]:
        """
        Return list of instances of class FileDescr for a given directory
        and all its subdirectories on the camera memory card.

        :param dir: camera's image directory, default '/DCIM'
        :type dir: *str*
        :returns: list of instances of class *FileDescr*
        """
        try:
            result = self.send_command('get_imglist', DIR=dir)
        except ResultError as e:
            if e.response.status_code == 404: # camera returns error 404
                return []                     # for an empty directory
            raise
        images = []
        for line in result.text.split('\r\n'):
            components = line.split(',')
            if len(components) != 6:
                continue
            path = '/'.join(components[:2])
            size, attrib, date, time = [int(cmp) for cmp in components[2:]]
            datetime = f'{1980+(date>>9)}-{(date>>5)&15:02d}-{date&31:02d}'\
                       f'T{time>>11:02d}:{(time>>5)&63:02d}:{2*(time&31):02d}'
            if attrib & 2: # hidden
                print(f"Ignoring hidden file '{path}'.")
                continue
            if attrib & 4: # system
                print(f"Ignoring system file '{path}'.")
                continue
            if attrib & 8: # volume
                print(f"Ignoring volume '{path}'.")
                continue
            if attrib & 16: # directory
                images += self.list_images(path)
            else:
                images.append(self.FileDescr(path, size, datetime))
        return images

    def download_thumbnail(self, dir: str) -> bytes:
        """
        Returns a thumbnail jpeg image.

        :param dir: path to image on camera
        :type dir: *str*
        :returns: JPEG image
        """
        return self.send_command('get_thumbnail', DIR=dir).content

    def download_image(self, dir: str) -> bytes:
        """
        Returns full-size jpeg image.

        :param dir: path to image on camera
        :type dir: *str*
        :returns: JPEG image
        """
        return requests.get(self.URL_PREFIX + dir[1:],
                            headers=self.HEADERS).content

    def start_liveview(self, port: int, lvqty: str) -> List[str]:
        """
        Start the liveview; the camera will broadcast an RTP live stream at the
        given UDP port in the given resolution. Supported values for the
        resolution can be queried with method:

        get_commands()['switch_cammode'].args['mode']['rec']['lvqty']

        :param port: UDP port for camera to broadcast RTP packages
        :type port: *int*
        :param lvqty: resolution of live stream
        :type lvqty: *str*
        :returns: list of funcid names that will be in the RTP extension.
        """
        self.send_command('switch_cammode', mode='rec', lvqty=lvqty)
        xml = self.send_command('exec_takemisc', com='startliveview',
                                port=port).text
        if xml and xml.startswith("<?xml "):
            return [funcid.attrib['name']
                    for funcid in ElementTree.fromstring(xml)
                    if funcid.tag == 'funcid' and 'name' in funcid.attrib]
        return []

    def stop_liveview(self) -> None:
        """
        Stop the liveview; the camera will no longer send the RTP live stream.
        """
        self.send_command('exec_takemisc', com='stopliveview')

    def report_model(self) -> None:
        """
        Report camera model and version info.

        :returns: Nothing; the camera model and version are written to *stdout*.
        """
        if 'model' in self.get_camera_info():
            model = self.get_camera_info()['model']
            versions = ', '.join([f'{key} {value}' for key, value in
                                  self.get_versions().items()])
            print(f"Connected to Olympus {model}, {versions}.")

class EM10Mk4(OlympusCamera):
    def take_picture(self) -> None:
        """
        The camera takes a picture.
        """

        self.send_command('switch_cammode', mode='rec')
        time.sleep(0.5)
        self.send_command('exec_takemisc', com='startliveview', port='5555')
        time.sleep(0.5)

        self.send_command('exec_takemotion', com='starttake')
        time.sleep(0.5)
        self.send_command('exec_takemotion', com='stoptake')

    def report_model(self) -> None:
        """
        Report camera model and version info.

        :returns: Nothing; the camera model and version are written to *stdout*.
        """

        info = self.get_camera_info()
        model = info[2]['model']

        if 'model' == 'E-M10MarkIV':
            versions = ', '.join([f'{key} {value}' for key, value in
                                  self.get_versions().items()])
            print(f"Connected to Olympus {model}, {versions}.")
