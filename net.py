import urllib.request
from urllib.parse import urlsplit

LOOPBACK = ("127.0.0.1", "localhost", "::1")


class _SameHostAuthorization(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


opener = urllib.request.build_opener(_SameHostAuthorization)


def same_origin(a, b):
    first, second = urlsplit(a), urlsplit(b)
    return (first.scheme, first.netloc) == (second.scheme, second.netloc)


def secure_url(url):
    parts = urlsplit(url or "")
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK)
