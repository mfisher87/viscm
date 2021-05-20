NOTE: This is a fork of the original `viscm`_.
Despite being a very great tool for creating proper scientific colormaps (which I highly thank the creators for), the original `viscm`_ is not particularly user-friendly and has some issues that sometimes makes it unreliable.
Because of this, I am updating the package to be more user-friendly and support more different types of colormaps (including proper support of diverging colormaps and cyclic colormaps).
All colormaps that are in my `CMasher`_ package were made with this fork of ``viscm``.
After I am done with all of my modifications and additions, I hope to merge this fork back into the original, such that everyone can use this great piece of software with ease.


.. _viscm:: https://github.com/matplotlib/viscm
.. _CMasher:: https://github.com/1313e/CMasher


viscm
=====

This is a little tool for analyzing colormaps and creating new colormaps.

Try::

  $ pip install viscm
  $ viscm view jet
  $ viscm edit

There is some information available about how to interpret the
resulting visualizations and use the editor tool `on this website
<https://bids.github.io/colormap/>`_.

Downloads:
  https://pypi.python.org/pypi/viscm/

Code and bug tracker:
  https://github.com/matplotlib/viscm

Contact:
  Nathaniel J. Smith <njs@pobox.com> and Stéfan van der Walt <stefanv@berkeley.edu>

Dependencies:
  * Python 3.5+
  * `colorspacious <https://pypi.python.org/pypi/colorspacious>`_
  * Matplotlib
  * NumPy
  * CMasher (for providing several utility functions regarding colormaps)
  * GuiPy (for providing many PyQt5 utility widgets that make ``viscm`` much more responsive)

License:
  MIT, see LICENSE.txt for details.
