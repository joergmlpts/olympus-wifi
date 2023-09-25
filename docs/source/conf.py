# Configuration file for the Sphinx documentation builder.
import os, sys

# -- Project information

project = 'olympuswifi'
copyright = '2023, joergmlpts'
author = 'joergmlpts'

release = '0.9'
version = '0.9.0'

# -- General configuration

extensions = [
    'sphinx.ext.duration',
    'sphinx.ext.doctest',
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.intersphinx',
]

intersphinx_mapping = {
    'python': ('https://docs.python.org/3/', None),
    'sphinx': ('https://www.sphinx-doc.org/en/master/', None),
}
intersphinx_disabled_domains = ['std']

templates_path = ['_templates']

autodoc_mock_imports = ['PIL', 'requests']

# -- Options for HTML output

html_theme = 'sphinx_rtd_theme'

# -- Options for EPUB output
epub_show_urls = 'footnote'

sys.path.insert(0, os.path.abspath('../../src'))
