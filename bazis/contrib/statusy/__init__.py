try:
    from importlib.metadata import PackageNotFoundError, version
    __version__ = version('bazis-statusy')
except PackageNotFoundError:
    __version__ = 'dev'


from collections import defaultdict
from functools import partial, wraps

from django.utils.translation import gettext_lazy as _

from bazis.core.errors import JsonApiBazisError


TRANSIT_LINK_STORE = defaultdict(dict)
TRANSIT_VALIDATORS_STORE = defaultdict(dict)
TRANSIT_BEFORE_STORE = defaultdict(dict)
TRANSIT_AFTER_STORE = defaultdict(dict)


class TransitError(JsonApiBazisError):
    code = 'ERR_TRANSIT'
    title = _('Transition error')


def _register(store, func, name=None):
    # class and method name
    cls_name, method_name = func.__qualname__.split('.')
    # register transition labels
    store[cls_name][method_name] = name or method_name


def transit_link(name=None):
    """
    Returns a wrap function that checks whether such a transition is allowed for the given object.
    The decorated function also acts as a filter to verify the admissibility of the transition.
    The wrap function returns a partial object with a pre-set transit parameter if the transition is allowed.
    """

    def decor(func):
        _register(TRANSIT_LINK_STORE, func, name)

        @wraps(func)
        def wrap(self, *args, **kwargs):
            transit = (
                [
                    t
                    for t in self.instance_transits
                    if func.__name__ == t.source_link and func(self, *args, **kwargs)
                ]
                + [None]
            )[0]
            if transit:
                return partial(self.transit_apply, transit)

        return wrap

    return decor


def transit_validator(name=None):
    """
    The validator is called before executing the transition; it can raise a TransitError exception.
    """

    def decor(func):
        _register(TRANSIT_VALIDATORS_STORE, func, name)
        return func

    return decor


def transit_before(name=None):
    def decor(func):
        _register(TRANSIT_BEFORE_STORE, func, name)
        return func

    return decor


def transit_after(name=None):
    def decor(func):
        _register(TRANSIT_AFTER_STORE, func, name)
        return func

    return decor
