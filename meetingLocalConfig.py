import re
from . import writers


class Config(object):
    logFileDir = '/var/www/meetbot/'
    filenamePattern = '%(channel)s/%%Y/%(channel)s.%%F-%%H.%%M'

    logUrlPrefix = 'https://meetbot.hellomouse.net/'
    MeetBotInfoURL = 'https://wiki.ubuntu.com/meetingology'
    moinFullLogs = True
    writer_map = {
        '.log.html': writers.HTMLlog,
        '.html': writers.HTML,
        # '.rst': writers.ReST,
        # '.txt': writers.Text,
        # '.rst.html': writers.HTMLfromReST,
        # '.moin.txt': writers.Moin,
        # '.mw.txt': writers.MediaWiki,
    }
    command_RE = re.compile(r'^[#\[](\w+)\]?(?:\s+(.*?)|)\s*$')
