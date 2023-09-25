.. _api:

API Overview
============

Several of the modules may be useful for other software. Class *OlympiaCamera*
communicates with the camera. This class allows to send commands to the camera
and it converts the camera's XML responses into Python dicts. These member
functions are particularly useful:

.. code-block:: console

   from olympuswifi.camera import OlympiaCamera

   camera = OlympiaCamera()

Upon initialization the *OlympiaCamera* class issues command *get_commandlist*
and uses this information about all the camera commands and command options
to check further requests to the camera.

.. code-block:: console

   camera.send_command('command', option1=value, ...)

Sends the command to the camera and returns a *requests.Response* object if
successful. On error, it will print an error message and return *None*.

.. code-block:: console

   camera.xml_query('command', option1=value1, ...)

Sends a command to the camera, parses the XML result and returns the result as
a Python *dict*. In case of an error it will print an error message and return
*None*. To obtain the AGPS expiration date as in the example above, we can call
*camera.xml_query('get_agpsinfo')['expiredate']* to get the result *20221111*
as a string.

.. code-block:: console

   camera.set_clock()

Sets date and time.

.. code-block:: console

   camera.get_images()

Returns a list of all images on the camera. For each each image there is the
file name including directory path, the size in bytes, and the date and time in
ISO format. 

.. code-block:: console

   camera.download_thumbnail('/DCIM/100OLYMP/PA220001.JPG')
   camera.download_image('/DCIM/100OLYMP/PA220001.JPG')

Returns the image thumbnail and the full image respectively.


Detailed API Documentation
==========================

Module camera
-------------

.. automodule:: olympuswifi.camera
   :members:

Module download
---------------

.. automodule:: olympuswifi.download
   :members:


Module liveview
---------------

.. automodule:: olympuswifi.liveview
   :members:

Module main
-----------

.. automodule:: olympuswifi.main
   :members:

Module log2gpx
--------------

.. automodule:: olympuswifi.log2gpx
   :members:
