# -*- coding: utf-8 -*-
# TODO(speakfreely)
"""分析这个项目【/Users/yang/project/reg-factory】，然后把这个项目的outlook里的注册移植到我们的项目里，并且不使用bit浏览器，我们自己做有头

Work in progress. Steps:
  1. Fetch the entry page and record routes/forms            [DONE]
  2. Extract fields, tokens, and required headers            [DONE]
  3. Replay the captured request(s) with variations          [DONE]
  4. Record status/body deltas into evidence/                [DONE]

Keep the helpers below unchanged.
"""
import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

EVIDENCE = "evidence"


def fetch(url, headers=None):
    request = urllib.request.Request(
        url, headers=headers or {"User-Agent": "assessment"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, response.read().decode("utf-8", "replace")


def save(name, payload):
    os.makedirs(EVIDENCE, exist_ok=True)
    path = os.path.join(EVIDENCE, name)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(payload, str):
            fh.write(payload)
        else:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


class _FieldParser(HTMLParser):
    """Collect form controls (and the first form's action/method) from HTML."""

    SKIP_TYPES = ("submit", "button", "reset", "file", "image")

    def __init__(self):
        HTMLParser.__init__(self)
        self.fields = {}
        self.action = ""
        self.method = "post"
        self._saw_form = False
        self._select_name = None
        self._select_value = None
        self._select_first = None
        self._textarea_name = None
        self._textarea_value = []

    def handle_starttag(self, tag, attrs):
        attrs = dict((key.lower(), value) for key, value in attrs)

        if tag == "form":
            if not self._saw_form:
                self.action = attrs.get("action") or ""
                self.method = (attrs.get("method") or "post").lower()
                self._saw_form = True
            return

        if tag == "input":
            name = attrs.get("name")
            if not name:
                return
            kind = (attrs.get("type") or "text").lower()
            if kind in self.SKIP_TYPES:
                return
            if kind in ("checkbox", "radio"):
                if "checked" not in attrs:
                    return
                self.fields[name] = attrs.get("value", "on")
            else:
                self.fields[name] = attrs.get("value", "")
            return

        if tag == "select":
            self._select_name = attrs.get("name")
            self._select_value = None
            self._select_first = None
            return

        if tag == "option" and self._select_name is not None:
            value = attrs.get("value")
            if value is None:
                value = ""
            if self._select_first is None:
                self._select_first = value
            if "selected" in attrs:
                self._select_value = value
            return

        if tag == "textarea":
            self._textarea_name = attrs.get("name")
            self._textarea_value = []

    def handle_data(self, data):
        if self._textarea_name is not None:
            self._textarea_value.append(data)

    def handle_endtag(self, tag):
        if tag == "select" and self._select_name is not None:
            value = self._select_value
            if value is None:
                value = self._select_first or ""
            self.fields[self._select_name] = value
            self._select_name = None
        elif tag == "textarea" and self._textarea_name is not None:
            self.fields[self._textarea_name] = "".join(self._textarea_value).strip()
            self._textarea_name = None


def _make_session():
    """An opener with its own cookie jar, so logins survive across calls."""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _as_session(session):
    if session is None:
        return _make_session()
    if hasattr(session, "open"):
        return session
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(session))


def list_fields(html):
    """Return form fields as a name -> value dict.

    Hidden inputs (tokens) are included. The first form's target and verb are
    exposed as the reserved keys ``_action`` and ``_method`` so the mapping can
    be fed straight into :func:`build_request`.
    """
    parser = _FieldParser()
    parser.feed(html or "")
    parser.close()
    fields = dict(parser.fields)
    fields["_action"] = parser.action
    fields["_method"] = parser.method
    return fields


def build_request(fields, overrides=None):
    """Turn a field mapping into a replayable request description.

    ``overrides`` wins over the extracted values. The reserved keys ``url``,
    ``method`` and ``headers`` configure the request itself; every other key is
    sent as a form value.
    """
    fields = dict(fields or {})
    overrides = dict(overrides or {})

    url = overrides.pop("url", fields.pop("_action", ""))
    method = str(overrides.pop("method", fields.pop("_method", "post"))).upper()
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    headers.update(overrides.pop("headers", {}) or {})

    values = dict(fields)
    values.update(overrides)
    body = urllib.parse.urlencode(values)

    if method in ("GET", "HEAD"):
        if body:
            url = "{}{}{}".format(url, "&" if "?" in url else "?", body)
        body = ""

    return {
        "url": url,
        "method": method,
        "headers": headers,
        "body": body,
        "fields": values,
    }


def replay(session, request):
    """Send ``request`` through ``session`` and capture status/headers/body."""
    opener = _as_session(session)
    url = request.get("url", "")
    method = (request.get("method") or "GET").upper()
    body = request.get("body", "")
    headers = dict(request.get("headers") or {})
    data = body.encode("utf-8") if body and method not in ("GET", "HEAD") else None

    probe = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(probe, timeout=20) as response:
            text = response.read().decode("utf-8", "replace")
            return {
                "status": response.status,
                "headers": dict(response.headers),
                "body": text,
                "url": response.geturl(),
            }
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        return {
            "status": exc.code,
            "headers": dict(exc.headers or {}),
            "body": text,
            "url": getattr(exc, "url", url),
        }
    except urllib.error.URLError as exc:
        return {
            "status": 0,
            "headers": {},
            "body": "",
            "url": url,
            "error": str(exc.reason),
        }


def run_batch(targets, session=None):
    """Replay many targets with one session; persist results to evidence/.

    Each target is one of:
      - a dict of overrides (or a full request description with ``url``),
      - a ``(fields, overrides)`` pair,
      - a URL string.
    """
    opener = _as_session(session)
    results = []

    for target in targets or []:
        if isinstance(target, dict):
            if "url" in target and ("method" in target or "body" in target):
                request = target
            else:
                request = build_request(target)
        elif isinstance(target, (list, tuple)) and len(target) == 2:
            request = build_request(target[0], target[1])
        else:
            request = build_request({}, {"url": target})

        response = replay(opener, request)
        results.append(
            {
                "request": request,
                "status": response.get("status"),
                "url": response.get("url"),
                "body": response.get("body", ""),
                "error": response.get("error"),
            }
        )

    if results:
        save("batch_results.json", results)
    return results
