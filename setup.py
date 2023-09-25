from distutils.core import setup, Extension

def long_description() -> str:
    "Return contents of README.md as long package description."
    with open('README.md', 'rt', encoding='utf-8') as f:
        return f.read()

setup(name='inattrails',
      version='0.9.0',
      package_dir={'olympuswifi': 'src/olympuswifi'},
      packages=['olympuswifi'],
      author='joergmlpts',
      author_email='joergmlpts@outlook.com',
      description='Connect to wifi-enabled Olympus camera, show liveview, '
      'set the clock, take picture, download images, change settings, turn '
      'it off.',
      readme="README.md",
      long_description=long_description(),
      long_description_content_type='text/markdown',
      url='https://github.com/joergmlpts/olympus-wifi',
      classifier=[
          'Development Status :: 5 - Production/Stable',
          'Intended Audience :: Developers',
          'Intended Audience :: End Users/Desktop',
          'License :: OSI Approved :: MIT License',
          'Operating System :: POSIX',
          'Programming Language :: Python',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3 :: Only',
          'Programming Language :: Python :: 3.7',
          'Programming Language :: Python :: 3.8',
          'Programming Language :: Python :: 3.9',
          'Programming Language :: Python :: 3.10',
          'Programming Language :: Python :: 3.11',
          'Programming Language :: Python :: 3.12',
          'Programming Language :: Python :: 3.13',
      ],
      entry_points = {
              'console_scripts': [
                  'olympus-camera=olympuswifi.main:main',
                  'olympus-liveview=olympuswifi.liveview:main',
                  'olympus-download=olympuswifi.download:main',
                  'olympus-log2gpx=olympuswifi.log2gpx:main',
              ],              
          },
      python_requires='>=3.7',
      install_requires=['Pillow', 'requests'],
      )
