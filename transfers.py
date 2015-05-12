from __future__ import absolute_import, with_statement, print_function, division, unicode_literals

from collections import deque
from pathlib import Path
from tradeexcept import TradeException

import csv
import json
import math
import misc.progress as pbar
import platform
import time

try:
    import requests
    __requests = requests
except ImportError:
    __requests = None

def import_requests():
    global __requests
    global platform
    if __requests:
        return __requests

    if platform.system() == 'Linux':
        extra = (
            "\nUbuntu users: You may be able to install 'pip' "
            "with 'apt-get install python3-pip' and requets with "
            "'pip3 install --upgrade requests'."
        )
    elif platform.system() == 'Windows':
        extra = (
            "\nThis often happens if you have bits of 32-bit and "
            "64-bit Python installed.\n"
            "Consider using control panel to uninstall Python, "
            "delete the Python folder (usually C:\\Python34\\) "
            "and re-install Python."
        )
    else:
        extra = ""

    print(
        "ERROR: Unable to load the Python 'requests' package." + extra + "\n"
    )
    approval = input(
        "I can try and install the package automatically using 'pip'.\n"
        "Try to install 'requests' now (y/n)? "
    )
    if approval.lower() != 'y':
        raise TradeException("Missing package: 'requests'")

    try:
        import pip
    except ImportError as e:
        import platform
        raise TradeException(
            "Python 3.4.2 includes a package manager called 'pip', "
            "except it doesn't appear to be installed on your system:\n"
            "{}{}".format(str(e), extra)
        ) from None

    pip.main(["install", "--upgrade", "requests"])

    try:
        import requests
        __requests = requests
    except ImportError as e:
        raise TradeException(
            "The requests module did not install correctly.{}"
            .format(extra)
        ) from None

    return __requests


######################################################################
# Helpers

class HTTP404(TradeException):
    pass


def makeUnit(value):
    """
    Convert a value in bytes into a Kb, Mb, Gb etc.
    """

    units = [ 'B ', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB' ]
    unitSize = int(value)
    for unit in units:
        if unitSize <= 640:
            return "{:>5.01f}{}".format(unitSize, unit)
        unitSize /= 1024
    return None


def download(
            tdenv, url, localFile,
            headers=None,
            backup=False,
            shebang=None,
            chunkSize=4096,
        ):
    """
    Fetch data from a URL and save the output
    to a local file. Returns the response headers.

    tdenv:
        TradeEnv we're working under

    url:
        URL we're fetching (http, https or ftp)

    localFile:
        Name of the local file to open.

    headers:
        dict() of additional HTTP headers to send

    shebang:
        function to call on the first line
    """

    requests = import_requests()
    tdenv.NOTE("Requesting {}".format(url))
    req = requests.get(url, headers=headers or None, stream=True)
    req.raise_for_status()

    encoding = req.headers.get('content-encoding', 'uncompress')
    length = req.headers.get('content-length', None)

    if length is None:
        raise Exception("Remote server replied with invalid content-length.")
    length = int(length)
    if length <= 0:
        raise TradeException(
            "Remote server gave an empty response. Please try again later."
        )

    if tdenv.detail > 1:
        tdenv.NOTE("Downloading {} {}ed data", makeUnit(length), encoding)
    tdenv.DEBUG0(req.headers)

    # Figure out how much data we have
    if not tdenv.quiet:
        progBar = pbar.Progress(length, 20)

    actPath = Path(localFile)
    tmpPath = Path("tmp/{}.dl".format(actPath.name))

    histogram = deque()

    fetched = 0
    lastTime = started = time.time()
    with tmpPath.open("wb") as fh:
        for data in req.iter_content(chunk_size=chunkSize):
            fh.write(data)
            fetched += len(data)
            if shebang:
                bangLine = data.decode().partition("\n")[0]
                tdenv.DEBUG0("Checking shebang of {}", bangLine)
                shebang(bangLine)
                shebang = None
            if not tdenv.quiet:
                now = time.time()
                deltaT = max(now - lastTime, 0.001)
                lastTime = now
                if len(histogram) >= 15:
                    histogram.popleft()
                histogram.append(len(data) / deltaT)
                progBar.increment(
                    len(data),
                    postfix=lambda value, goal: \
                        " {:>7s} [{:>7s}/s] {:>3.0f}%".format(
                            makeUnit(value),
                            makeUnit(sum(histogram) / len(histogram)),
                            (fetched * 100. / length),
                        )
                )
        tdenv.DEBUG0("End of data")
    if not tdenv.quiet:
        progBar.clear()
        tdenv.NOTE(
            "Downloaded {} of {}ed data {}/s",
            makeUnit(fetched), encoding,
            makeUnit(fetched / (time.time() - started))
        )

    # Swap the file into place
    if backup:
        bakPath = Path(localFile + ".bak")
        if bakPath.exists():
            bakPath.unlink()
        if actPath.exists():
            actPath.rename(localFile + ".bak")
    if actPath.exists():
        actPath.unlink()
    tmpPath.rename(actPath)

    req.close()
    return req.headers


def get_json_data(url):
    """
    Fetch JSON data from a URL and return the resulting dictionary.

    Displays a progress bar as it downloads.
    """

    requests = import_requests()
    req = requests.get(url, stream=True)

    totalLength = req.headers.get('content-length')
    if totalLength is None:
        compression = req.headers.get('content-encoding')
        compression = (compression + "'ed") if compression else "uncompressed"
        print("Downloading {}: {}...".format(compression, url))
        jsData = req.content
    else:
        totalLength = int(totalLength)
        progBar = pbar.Progress(totalLength, 25)
        jsData = bytes()
        for data in req.iter_content():
            jsData += data
            progBar.increment(
                len(data),
                postfix=lambda value, goal: \
                " {}/{}".format(
                    makeUnit(value),
                    makeUnit(goal),
            ))
        progBar.clear()

    return json.loads(jsData.decode())


class CSVStream(object):
    """
    Provides an iterator that fetches CSV data from a given URL
    and presents it as an iterable of (columns, values).

    Example:
        stream = transfers.CSVStream("http://blah.com/foo.csv")
        for cols, vals in stream:
            print("{} = {}".format(cols[0], vals[0]))
    """

    def __init__(self, url, tdenv=None):
        self.url = url
        self.tdenv = tdenv
        if not url.startswith("file:///"):
            requests = import_requests()
            self.req = requests.get(self.url, stream=True)
            self.lines = self.req.iter_lines()
        else:
            self.lines = open(url[8:], "rUb")
        self.columns = self.next_line().split(',')

    def next_line(self):
        """ Fetch the next line as a text string """
        while True:
            line = next(self.lines)
            try:
                return line.decode(encoding="utf-8")
            except UnicodeDecodeError as e:
                if not self.tdenv:
                    raise e
                self.tdenv.WARN(
                    "{}: line:{}: {}\n{}",
                    self.url, self.csvin.line_num, line, e
                )

    def __iter__(self):
        """
        Iterate across data received as csv values.
        Yields [column headings], [column values]
        """
        self.csvin = csvin = csv.reader(
            iter(self.next_line, 'END'),
            delimiter=',', quotechar="'", doublequote=True
        )
        columns = self.columns
        for values in csvin:
            if values and len(values) == len(columns):
                yield columns, values
