# -*- coding: utf-8 -*-
"""
    Some py2/py3 compatibility support based on a stripped down
    version of six so we don't have to depend on a specific version
    of it.

    :copyright: (c) 2013 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""

import sys

PY2 = sys.version_info[0] == 2
VER = sys.version_info

if not PY2:
    text_type = str
    string_types = (str,)
    integer_types = (int,)

    iterkeys = lambda d: iter(d.keys())  # noqa
    itervalues = lambda d: iter(d.values())  # noqa
    iteritems = lambda d: iter(d.items())  # noqa

    def as_unicode(s):
        """
        Convert bytes or string to unicode string.
        
        Args:
            s: String or bytes to convert
            
        Returns:
            Unicode string representation
        """
        if isinstance(s, bytes):
            return s.decode('utf-8')
        return s

else:
    text_type = unicode  # noqa
    string_types = (basestring,)  # noqa
    integer_types = (int, long)  # noqa

    iterkeys = lambda d: d.iterkeys()  # noqa
    itervalues = lambda d: d.itervalues()  # noqa
    iteritems = lambda d: d.iteritems()  # noqa

    def as_unicode(s):
        """
        Convert string to unicode string (Python 2 compatibility).
        
        Args:
            s: String to convert
            
        Returns:
            Unicode string representation
        """
        if isinstance(s, str):
            return s.decode('utf-8')
        return unicode(s)  # noqa