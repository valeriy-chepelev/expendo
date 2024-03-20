import shelve
import functools
from hashlib import md5
from base64 import b64encode


def issue_cache(file_name):
    d = shelve.open(file_name)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(issue):
            h = md5(str(func.__name__ + issue.key).encode())
            key = b64encode(h.digest()).decode()
            if key not in d:
                d[key] = func(issue)
            return d[key]

        return wrapper

    return decorator


def clear_issue_cache(file_name):
    s = shelve.open(file_name, flag='n')
    s.close()
