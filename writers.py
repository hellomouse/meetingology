###
# Copyright (c) 2009, Richard Darst
# Copyright (c) 2018, Krytarik Raido
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

from __future__ import annotations

import os
import re
import time
import textwrap
from typing import Any, Callable, TYPE_CHECKING, Union

from . import __version__
if TYPE_CHECKING:
    from .meeting import Meeting

# Data sanitizing for various output methods


def html(text: str):
    """Escape bad sequences (in HTML) in user-generated lines."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


rstReplaceRE = re.compile('_( |-|$)')


def rst(text: str):
    """Escapes bad sequences in reST"""
    return rstReplaceRE.sub(r'\_\1', text)


def text(text: str):
    """Escapes bad sequences in text (not implemented yet)"""
    return text


def mw(text: str):
    """Escapes bad sequences in MediaWiki markup (not implemented yet)"""
    return text


def moin(text: str):
    """Escapes bad sequences in Moin Moin wiki markup (not implemented yet)"""
    return text


# wraping functions (for RST)
class TextWrapper(textwrap.TextWrapper):
    wordsep_re = re.compile(r'(\s+)')


def wrapList(item: str, indent: int = 0):
    return TextWrapper(width=72, initial_indent=' '*indent,
                       subsequent_indent=' '*(indent+2),
                       break_long_words=False).fill(item)


def indentItem(item: str, indent: int = 0):
    return ' '*indent + item


def replaceWRAP(item: str):
    re_wrap = re.compile(r'sWRAPs(.*)eWRAPe', re.DOTALL)

    def repl(m):
        return TextWrapper(width=72, break_long_words=False).fill(m.group(1))
    return re_wrap.sub(repl, item)


class _BaseWriter(object):
    def __init__(self, M: Meeting, **kwargs):
        self.M = M

    def format(self, extension: str = None):
        """Override this method to implement the formatting.

        For file output writers, the method should return a unicode
        object containing the contents of the file to write.

        The argument 'extension' is the key from `writer_map`.  For
        file writers, this can (and should) be ignored.  For non-file
        outputs, this can be used to This can be used to pass data,
        """
        raise NotImplementedError

    @property
    def pagetitle(self):
        if self.M._meetingTopic:
            title = "%s: %s" % (self.M.channel, self.M._meetingTopic)
            if "meeting" not in self.M._meetingTopic.lower():
                title += ' meeting'
            return title
        return "%s meeting" % self.M.channel

    def replacements(self):
        return {'pageTitle': self.pagetitle,
                'owner': self.M.owner,
                'starttime': time.strftime("%H:%M:%S", self.M.starttime),
                'starttimeshort': time.strftime("%H:%M", self.M.starttime),
                'startdate': time.strftime("%d %b", self.M.starttime),
                'endtime': time.strftime("%H:%M:%S", self.M.endtime),
                'endtimeshort': time.strftime("%H:%M", self.M.endtime),
                'timeZone': self.M.config.timeZone,
                'fullLogs': f"{self.M.config.basename}.log.html",
                'fullLogsFullURL': f"{self.M.config.filename(url=True)}.log.html",
                'MeetBotInfoURL': self.M.config.MeetBotInfoURL,
                'MeetBotVersion': __version__,
                }

    def iterNickCounts(self):
        nicks = [(n, c) for (n, c) in self.M.attendees.items()]
        nicks.sort(key=lambda x: x[1], reverse=True)
        return nicks

    def iterActionItemsNick(self):
        for nick in sorted(self.M.attendees.keys(), key=lambda x: x.lower()):
            def nickitems():
                for m in self.M.minutes:
                    # The hack below is needed because of pickling problems
                    if m.itemtype != "ACTION":
                        continue
                    if not re.match(r'.*\b%s\b.*' % re.escape(nick), m.line, re.I):
                        continue
                    m.assigned = True
                    yield m
            yield nick, nickitems()

    def iterActionItemsUnassigned(self):
        for m in self.M.minutes:
            if m.itemtype != "ACTION":
                continue
            if getattr(m, 'assigned', False):
                continue
            yield m

    def get_template(self, escape: Callable = lambda s: s):
        M = self.M
        repl = self.replacements()

        MeetingItems = []
        # We can have initial items with NO initial topic.  This
        # messes up the templating, so, have this null topic as a
        # stopgap measure.
        nextTopic = {'topic': {'itemtype': 'TOPIC', 'topic': 'Prologue',
                               'nick': '',
                               'time': '', 'link': '', 'anchor': ''},
                     'items': []}
        haveTopic = False
        for m in M.minutes:
            if m.itemtype == "TOPIC":
                if nextTopic['topic']['nick'] or nextTopic['items']:
                    MeetingItems.append(nextTopic)
                nextTopic = {'topic': m.template(M, escape), 'items': []}
                haveTopic = True
            else:
                nextTopic['items'].append(m.template(M, escape))
        MeetingItems.append(nextTopic)
        repl['MeetingItems'] = MeetingItems
        # Format of MeetingItems:
        # [ {'topic': {item_dict},
        #    'items': [item_dict, item_object, item_object, ...]
        #    },
        #   { 'topic':...
        #     'items':...
        #    },
        #   ....
        # ]
        #
        # an item_dict has:
        # item_dict = {'itemtype': TOPIC, ACTION, IDEA, or so on...
        #              'line': the actual line that was said
        #              'nick': nick of who said the line
        #              'time': 10:53:15, for example, the time
        #              'link': ${link}#${anchor} is the URL to link to.
        #                      (page name, and bookmark)
        #              'anchor': see above
        #              'topic': if itemtype is TOPIC, 'line' is not given,
        #                      instead we have 'topic'
        #              'url':  if itemtype is LINK, the line should be created
        #                      by "${link} ${line}", where 'link' is the URL
        #                      to link to, and 'line' is the rest of the line
        #                      (that isn't a URL)
        #              'url_quoteescaped': 'url' but with " escaped for use in
        #                                  <a href="$url_quoteescaped">
        ActionItems = []
        for m in M.minutes:
            if m.itemtype != "ACTION":
                continue
            ActionItems.append(escape(m.line))
        repl['ActionItems'] = ActionItems
        # Format of ActionItems: It's just a very simple list of lines.
        # [line, line, line, ...]
        # line = (string of what it is)

        ActionItemsPerson = []
        numberAssigned = 0
        for nick, items in self.iterActionItemsNick():
            thisNick = {'nick': escape(nick), 'items': []}
            for m in items:
                numberAssigned += 1
                thisNick['items'].append(escape(m.line))
            if len(thisNick['items']) > 0:
                ActionItemsPerson.append(thisNick)
        # Work on the unassigned nicks.
        thisNick = {'nick': 'UNASSIGNED', 'items': []}
        for m in self.iterActionItemsUnassigned():
            thisNick['items'].append(escape(m.line))
        if len(thisNick['items']) > 1:
            ActionItemsPerson.append(thisNick)
        # if numberAssigned == 0:
        #    ActionItemsPerson = None
        repl['ActionItemsPerson'] = ActionItemsPerson
        # Format of ActionItemsPerson
        # ActionItemsPerson =
        #  [ {'nick':nick_of_person,
        #     'items': [item1, item2, item3, ...],
        #    },
        #   ...,
        #   ...,
        #    {'nick':'UNASSIGNED',
        #     'items': [item1, item2, item3, ...],
        #    }
        #  ]

        PeoplePresent = []
        # sort by number of lines spoken
        for nick, count in self.iterNickCounts():
            PeoplePresent.append({'nick': escape(nick),
                                  'count': count})
        repl['PeoplePresent'] = PeoplePresent
        # Format of PeoplePresent
        # [{'nick':the_nick, 'count':count_of_lines_said},
        #  ...,
        #  ...,
        # ]

        return repl

    def get_template2(self, escape: Callable = lambda s: s):
        # let's make the data structure easier to use in the template
        repl = self.get_template(escape=escape)
        repl = {
            'time':           {'start': repl['starttime'], 'end': repl['endtime'], 'timezone': repl['timeZone']},
            'meeting':        {'title': repl['pageTitle'], 'owner': repl['owner'], 'logs': repl['fullLogs'], 'logsFullURL': repl['fullLogsFullURL']},
            'attendees':      [person for person in repl['PeoplePresent']],
            'agenda':         [{'topic': item['topic'], 'notes': item['items']} for item in repl['MeetingItems']],
            'actions':        [action for action in repl['ActionItems']],
            'actions_person': [{'nick': attendee['nick'], 'actions': attendee['items']} for attendee in repl['ActionItemsPerson']],
            'meetbot':        {'version': repl['MeetBotVersion'], 'url': repl['MeetBotInfoURL']},
        }
        return repl


class Template(_BaseWriter):
    """Format a notes file using the genshi templating engine

    Send an argument template=<filename> to specify which template to
    use.  If `template` begins in '+', then it is relative to the
    MeetBot source directory.  Included templates are:
      +template.html
      +template.txt

    Some examples of using these options are:
      writer_map['.txt|template=+template.html'] = writers.Template
      writer_map['.txt|template=/home/you/template.txt] = writers.Template

    If a template ends in .txt, parse with a text-based genshi
    templater.  Otherwise, parse with a HTML-based genshi templater.
    """

    def format(self, extension: str = None, template: str = '+template.html'):
        repl = self.get_template2()

        # If `template` begins in '+', then it in relative to the
        # MeetBot source directory.
        if template[0] == '+':
            template = os.path.join(os.path.dirname(__file__), template[1:])
        # If we don't test here, it might fail in the try: block
        # below, then f.close() will fail and mask the original
        # exception
        if not os.access(template, os.F_OK):
            raise IOError('File not found: %s' % template)

        # Do we want to use a text template or HTML ?
        import genshi.template
        if template[-4:] in ('.txt', '.rst'):
            Template = genshi.template.NewTextTemplate   # plain text
        else:
            Template = genshi.template.MarkupTemplate    # HTML-like

        # Do the actual templating work
        with open(template, 'r') as f:
            tmpl = Template(f.read())
            stream = tmpl.generate(**repl)

        return stream.render()


class _CSSmanager(object):
    _css_head = textwrap.dedent('''\
        <style type="text/css">
        %s
        </style>
        ''')

    def getCSS(self, name: str):
        cssfile = getattr(self.M.config, f'cssFile_{name}', '')
        if cssfile.lower() == 'none':
            # special string 'None' means no style at all
            return ''
        elif cssfile in ('', 'default'):
            # default CSS file
            css_fname = os.path.join(os.path.dirname(__file__),
                                     f'css-{name}-default.css')
        else:
            css_fname = cssfile
        try:
            # Stylesheet specified
            if getattr(self.M.config, f'cssEmbed_{name}', True):
                # external stylesheet
                with open(css_fname) as f:
                    css = f.read()
                return self._css_head % css
            else:
                # linked stylesheet
                css_head = ('''<link rel="stylesheet" type="text/css" '''
                            '''href="/%s">''' % css_fname.split("/")[-1])
                return css_head
        except Exception as exc:
            if not self.M.config.safeMode:
                raise
            import traceback
            traceback.print_exc()
            print("(exception above ignored, continuing)")
            try:
                css_fname = os.path.join(os.path.dirname(__file__),
                                         f'css-{name}-default.css')
                with open(css_fname) as f:
                    css = f.read()
                return self._css_head % css
            except Exception:
                if not self.M.config.safeMode:
                    raise
                traceback.print_exc()
                return ''


class TextLog(_BaseWriter):
    def format(self, extension: str = None):
        M = self.M
        """Write raw text logs."""
        return "\n".join(M.lines)
    update_realtime = True


class HTMLlog(_BaseWriter, _CSSmanager):
    def format(self, extension: str = None) -> str:
        """Write pretty HTML logs."""
        M = self.M
        lines = []
        line_re = re.compile(r"""\s*
            (?P<time> \[?[0-9:\s]*\]?)\s*
            (?P<nick>\s+<[@+\s]?[^>]+>)\s*
            (?P<line>.*)
        """, re.VERBOSE)
        action_re = re.compile(r"""\s*
            (?P<time> \[?[0-9:\s]*\]?)\s*
            (?P<nick>\*\s+[@+\s]?[^\s]+)\s*
            (?P<line>.*)
        """, re.VERBOSE)
        command_re = re.compile(r"(#[^\s]+[ \t\f\v]*)(.*)")
        command_topic_re = re.compile(r"(#topic[ \t\f\v]*)(.*)")
        hilight_re = re.compile(r"([^\s]+:)( .*)")
        lineNumber = 0
        for l in M.lines:
            lineNumber += 1  # starts from 1
            # is it a regular line?
            m = line_re.match(l)
            if m:
                line = m.group('line')
                # Match #topic
                m2 = command_topic_re.match(line)
                if m2:
                    outline = ('<span class="topic">%s</span>'
                               '<span class="topicline">%s</span>' %
                               (html(m2.group(1)), html(m2.group(2))))
                # Match other #commands
                if not m2:
                    m2 = command_re.match(line)
                    if m2:
                        outline = ('<span class="cmd">%s</span>'
                                   '<span class="cmdline">%s</span>' %
                                   (html(m2.group(1)), html(m2.group(2))))
                # match hilights
                if not m2:
                    m2 = hilight_re.match(line)
                    if m2:
                        outline = ('<span class="hi">%s</span>' '%s' %
                                   (html(m2.group(1)), html(m2.group(2))))
                if not m2:
                    outline = html(line)
                lines.append('<a href="#l-%(lineno)s" name="l-%(lineno)s">'
                             '<span class="tm">%(time)s</span></a>'
                             '<span class="nk">%(nick)s</span> '
                             '%(line)s' % {'lineno': lineNumber,
                                           'time': html(m.group('time')),
                                           'nick': html(m.group('nick')),
                                           'line': outline,
                                           })
                continue
            m = action_re.match(l)
            # is it a action line?
            if m:
                lines.append('<a name="l-%(lineno)s"></a>'
                             '<span class="tm">%(time)s</span>'
                             '<span class="nka">%(nick)s</span> '
                             '<span class="ac">%(line)s</span>' %
                             {'lineno': lineNumber,
                              'time': html(m.group('time')),
                              'nick': html(m.group('nick')),
                              'line': html(m.group('line')),
                              })
                continue
            print(l)
            print(m.groups())
            print("**error**", l)

        css = self.getCSS(name='log')
        return html_template % {'pageTitle': "%s log" % html(M.channel),
                                # 'body':"<br>\n".join(lines),
                                'body': "<pre>"+("\n".join(lines))+"</pre>",
                                'headExtra': css,
                                }


html_template = textwrap.dedent('''\
    <!DOCTYPE HTML>
    <html>
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>%(pageTitle)s</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-EVSTQN3/azprG1Anm3QDgpJLIm9Nao0Yz1ztcQTwFspd3yD65VohhpuuCOmLASjC" crossorigin="anonymous">
    %(headExtra)s
    </head>

    <body>
    <div class="container-fluid">
    %(body)s
    </div>
    </body>
    </html>
    ''')


class HTML(_BaseWriter, _CSSmanager):
    """HTML formatter without tables."""

    def meetingItems(self):
        """Return the main 'Meeting minutes' block."""
        M = self.M

        # Add all minute items to the table
        MeetingItems: list[str] = []
        MeetingItems.append(self.heading('Meeting summary'))
        MeetingItems.append('<ol class="summary">')

        haveTopic = False
        haveSubtopic = False
        inSublist = False
        inSubsublist = False
        for m in M.minutes:
            item = f"<li>{m.html(M)}"
            if m.itemtype == "TOPIC":
                if inSublist:
                    MeetingItems.append(indentItem("</ol>", 4))
                    inSublist = False
                if haveSubtopic:
                    if inSubsublist:
                        MeetingItems.append(indentItem("</ol>", 8))
                        inSubsublist = False
                    MeetingItems.append(indentItem("</li>", 6))
                    haveSubtopic = False
                if haveTopic:
                    MeetingItems.append(indentItem("</li>", 2))
                item = wrapList(item, 2)
                haveTopic = True
            elif m.itemtype == "SUBTOPIC":
                if not inSublist:
                    if not haveTopic:
                        MeetingItems.append(indentItem("<li>", 2))
                        haveTopic = True
                    MeetingItems.append(indentItem('<ol type="a">', 4))
                    inSublist = True
                item = wrapList(item, 6)
                haveSubtopic = True
            else:
                if not inSublist:
                    if not haveTopic:
                        MeetingItems.append(indentItem("<li>", 2))
                        haveTopic = True
                    MeetingItems.append(indentItem('<ol type="a">', 4))
                    inSublist = True
                if haveSubtopic:
                    if not inSubsublist:
                        MeetingItems.append(indentItem('<ol type="i">', 8))
                        inSubsublist = True
                    item = wrapList(item, 10)+"</li>"
                elif haveTopic:
                    item = wrapList(item, 6)+"</li>"
                else:
                    item = wrapList(item, 2)+"</li>"
            MeetingItems.append(item)

        if haveSubtopic:
            if inSubsublist:
                MeetingItems.append(indentItem("</ol>", 8))
            MeetingItems.append(indentItem("</li>", 6))
        if inSublist:
            MeetingItems.append(indentItem("</ol>", 4))
        if haveTopic:
            MeetingItems.append(indentItem("</li>", 2))

        MeetingItems.append("</ol>")
        MeetingItems = "\n".join(MeetingItems)
        return MeetingItems

    def votes(self) -> str:
        M = self.M
        # Votes
        Votes = []
        # reversed to show the oldest first
        for v, (vsum, vline) in M.votes.items():
            voteLink = "%(fullLogs)s" % self.replacements()
            Votes.append(wrapList("<li><a href='%s#%d'>%s</a>" %
                         (voteLink, vline, html(v)), 2))
            # differentiate denied votes somehow, strikethrough perhaps?
            Votes.append(wrapList("<ul><li>%s" % html(vsum), 4))
            if M.publicVoters[v]:
                publicVoters = ', '.join(M.publicVoters[v])
                Votes.append(wrapList("<ul><li>Voters: %s</li></ul>" %
                             html(publicVoters), 6))
        if not Votes:
            return None
        Votes.insert(0, '<ol>')
        Votes.insert(0, self.heading('Vote results'))
        Votes.append(indentItem('</li></ul>', 4))
        Votes.append(indentItem('</li>', 2))
        Votes.append('</ol>')
        Votes = "\n".join(Votes)
        return Votes

    def actionItems(self) -> str:
        """Return the 'Action items' block."""
        M = self.M
        # Action Items
        ActionItems = []
        for m in M.minutes:
            # The hack below is needed because of pickling problems
            if m.itemtype != "ACTION":
                continue
            ActionItems.append(wrapList("<li>%s</li>" % html(m.line), 2))
        if not ActionItems:
            return None
        ActionItems.insert(0, '<ol>')
        ActionItems.insert(0, self.heading('Action items'))
        ActionItems.append('</ol>')
        ActionItems = "\n".join(ActionItems)
        return ActionItems

    def actionItemsPerson(self) -> str:
        """Return the 'Action items, by person' block."""
        M = self.M
        # Action Items, by person (This could be made lots more efficient)
        ActionItemsPerson = []
        for nick, items in self.iterActionItemsNick():
            headerPrinted = False
            for m in items:
                if not headerPrinted:
                    ActionItemsPerson.append(indentItem(
                        '<li>%s<ol type="a">' % html(nick), 2))
                    headerPrinted = True
                ActionItemsPerson.append(
                    wrapList("<li>%s</li>" % html(m.line), 4))
            if headerPrinted:
                ActionItemsPerson.append(indentItem('</ol></li>', 2))
        if not ActionItemsPerson:
            return None

        # Unassigned items
        Unassigned = []
        for m in self.iterActionItemsUnassigned():
            Unassigned.append(wrapList("<li>%s</li>" % html(m.line), 4))
        if Unassigned:
            Unassigned.insert(0, indentItem("<li><b>UNASSIGNED</b><ol>", 2))
            Unassigned.append(indentItem('</ol></li>', 2))
            ActionItemsPerson.extend(Unassigned)

        ActionItemsPerson.insert(0, '<ol>')
        ActionItemsPerson.insert(0, self.heading('Action items, by person'))
        ActionItemsPerson.append('</ol>')
        ActionItemsPerson = "\n".join(ActionItemsPerson)
        return ActionItemsPerson

    def doneItems(self) -> str:
        M = self.M
        # Done Items
        DoneItems = []
        for m in M.minutes:
            # The hack below is needed because of pickling problems
            if m.itemtype != "DONE":
                continue
            # already escaped
            DoneItems.append(wrapList("<li>%s</li>" % html(m.line), 2))
        if not DoneItems:
            return None
        DoneItems.insert(0, '<ol>')
        DoneItems.insert(0, self.heading('Done items'))
        DoneItems.append('</ol>')
        DoneItems = "\n".join(DoneItems)
        return DoneItems

    def peoplePresent(self) -> str:
        """Return the 'People present' block."""
        # People Attending
        PeoplePresent = []
        PeoplePresent.append(self.heading('People present (lines said)'))
        PeoplePresent.append('<ol>')
        # sort by number of lines spoken
        for nick, count in self.iterNickCounts():
            PeoplePresent.append(indentItem(
                '<li>%s (%d)</li>' % (html(nick), count), 2))
        PeoplePresent.append('</ol>')
        PeoplePresent = "\n".join(PeoplePresent)
        return PeoplePresent

    def heading(self, name: str) -> str:
        return '<h3>%s</h3>' % name

    def format(self, extension: str = None) -> str:
        """Write the minutes summary."""
        M = self.M

        repl = self.replacements()

        body = []
        body.append(textwrap.dedent("""\
            <h1>%(pageTitle)s</h1>
            <div class="details">
            Meeting started by %(owner)s at %(starttime)s %(timeZone)s
            (<a href="%(fullLogs)s">full logs</a>)</div>""" % repl))
        body.append(self.meetingItems())
        body.append(textwrap.dedent("""\
            <div class="details">
            Meeting ended at %(endtime)s %(timeZone)s
            (<a href="%(fullLogs)s">full logs</a>)</div>""" % repl))
        body.append(self.actionItems())
        body.append(self.actionItemsPerson())
        body.append(self.peoplePresent())
        body.append("""<div class="details">"""
                    """Generated by <a href="%(MeetBotInfoURL)s">MeetBot</a> """
                    """%(MeetBotVersion)s</div>""" % repl)
        body = [b for b in body if b is not None]
        body = "\n\n\n\n".join(body)
        body = replaceWRAP(body)

        css = self.getCSS(name='minutes')
        repl.update({'body': body,
                     'headExtra': css,
                     })
        html = html_template % repl

        return html


class ReST(_BaseWriter):
    body = textwrap.dedent("""\
    %(titleBlock)s
    %(pageTitle)s
    %(titleBlock)s


    sWRAPsMeeting started by %(owner)s at %(starttime)s %(timeZone)s
    (`full logs`_)eWRAPe

    .. _`full logs`: %(fullLogs)s




    Meeting summary
    ---------------
    %(MeetingItems)s

    Meeting ended at %(endtime)s %(timeZone)s (`full logs`_)

    .. _`full logs`: %(fullLogs)s




    Action items
    ------------
    %(ActionItems)s




    Action items, by person
    -----------------------
    %(ActionItemsPerson)s




    People present (lines said)
    ---------------------------
    %(PeoplePresent)s




    Generated by `MeetBot`_ %(MeetBotVersion)s

    .. _`MeetBot`: %(MeetBotInfoURL)s
    """)

    def format(self, extension: str = None) -> str:
        """Return a ReStructured Text minutes summary."""
        M = self.M
        # Agenda items
        MeetingItems = []
        M.rst_urls = []
        M.rst_refs = {}
        haveTopic = False
        for m in M.minutes:
            item = "* "+m.rst(M)
            if m.itemtype == "TOPIC":
                if haveTopic:
                    MeetingItems.append("")
                item = wrapList(item, 0)
                haveTopic = True
            else:
                if haveTopic:
                    item = wrapList(item, 2)
                else:
                    item = wrapList(item, 0)
            MeetingItems.append(item)
        MeetingItems = "\n\n".join(MeetingItems)
        MeetingURLs = "\n".join(M.rst_urls)
        del M.rst_urls, M.rst_refs
        MeetingItems += "\n\n"+MeetingURLs

        # Action Items
        ActionItems = []
        for m in M.minutes:
            # The hack below is needed because of pickling problems
            if m.itemtype != "ACTION":
                continue
            # already escaped
            ActionItems.append(wrapList("* %s" % rst(m.line), 0))
        if not ActionItems:
            ActionItems.append("* (None)")
        ActionItems = "\n\n".join(ActionItems)

        # Action Items, by person (This could be made lots more efficient)
        ActionItemsPerson = []
        for nick in sorted(M.attendees.keys(), key=lambda x: x.lower()):
            headerPrinted = False
            for m in M.minutes:
                # The hack below is needed because of pickling problems
                if m.itemtype != "ACTION":
                    continue
                if not re.match(r'.*\b%s\b.*' % re.escape(nick), m.line, re.I):
                    continue
                if not headerPrinted:
                    ActionItemsPerson.append("* %s" % rst(nick))
                    headerPrinted = True
                ActionItemsPerson.append(wrapList("* %s" % rst(m.line), 2))
                m.assigned = True
        if not ActionItemsPerson:
            ActionItemsPerson.append("* (None)")
        else:
            # Unassigned items
            Unassigned = []
            for m in M.minutes:
                if m.itemtype != "ACTION":
                    continue
                if getattr(m, 'assigned', False):
                    continue
                Unassigned.append(wrapList("* %s" % rst(m.line), 2))
            if Unassigned:
                Unassigned.insert(0, "* **UNASSIGNED**")
                ActionItemsPerson.extend(Unassigned)
        ActionItemsPerson = "\n\n".join(ActionItemsPerson)

        # People Attending
        PeoplePresent = []
        # sort by number of lines spoken
        for nick, count in self.iterNickCounts():
            PeoplePresent.append('* %s (%d)' % (rst(nick), count))
        PeoplePresent = "\n\n".join(PeoplePresent)

        # Actual formatting and replacement
        repl = self.replacements()
        repl.update({'titleBlock': ('='*len(repl['pageTitle'])),
                     'MeetingItems': MeetingItems,
                     'ActionItems': ActionItems,
                     'ActionItemsPerson': ActionItemsPerson,
                     'PeoplePresent': PeoplePresent,
                     })
        body = self.body
        body = body % repl
        body = replaceWRAP(body)
        return body


class HTMLfromReST(_BaseWriter):
    def format(self, extension: str = None):
        M = self.M
        import docutils.core
        rst = ReST(M).format(extension)
        rstToHTML = docutils.core.publish_string(rst, writer_name='html',
                                                 settings_overrides={'file_insertion_enabled': 0,
                                                                     'raw_enabled': 0,
                                                                     'output_encoding': self.M.config.output_codec})
        return rstToHTML


class Text(_BaseWriter):
    def meetingItems(self) -> str:
        M = self.M
        # Agenda items
        MeetingItems = []
        MeetingItems.append(self.heading('Meeting summary'))
        haveTopic = False
        for m in M.minutes:
            item = "* "+m.text(M)
            if m.itemtype == "TOPIC":
                if haveTopic:
                    MeetingItems.append("")
                item = wrapList(item, 0)
                haveTopic = True
            else:
                if haveTopic:
                    item = wrapList(item, 2)
                else:
                    item = wrapList(item, 0)
            MeetingItems.append(item)
        MeetingItems = "\n".join(MeetingItems)
        return MeetingItems

    def actionItems(self) -> str:
        M = self.M
        # Action Items
        ActionItems = []
        for m in M.minutes:
            # The hack below is needed because of pickling problems
            if m.itemtype != "ACTION":
                continue
            # already escaped
            ActionItems.append(wrapList("* %s" % text(m.line), 0))
        if not ActionItems:
            return None
        ActionItems.insert(0, self.heading('Action items'))
        ActionItems = "\n".join(ActionItems)
        return ActionItems

    def actionItemsPerson(self) -> str:
        M = self.M
        # Action Items, by person (This could be made lots more efficient)
        ActionItemsPerson = []
        for nick in sorted(M.attendees.keys(), key=lambda x: x.lower()):
            headerPrinted = False
            for m in M.minutes:
                # The hack below is needed because of pickling problems
                if m.itemtype != "ACTION":
                    continue
                if not re.match(r'.*\b%s\b.*' % re.escape(nick), m.line, re.I):
                    continue
                if not headerPrinted:
                    ActionItemsPerson.append("* %s" % text(nick))
                    headerPrinted = True
                ActionItemsPerson.append(wrapList("* %s" % text(m.line), 2))
                m.assigned = True
        if not ActionItemsPerson:
            return None

        # Unassigned items
        Unassigned = []
        for m in M.minutes:
            if m.itemtype != "ACTION":
                continue
            if getattr(m, 'assigned', False):
                continue
            Unassigned.append(wrapList("* %s" % text(m.line), 2))
        if Unassigned:
            Unassigned.insert(0, "* **UNASSIGNED**")
            ActionItemsPerson.extend(Unassigned)

        ActionItemsPerson.insert(0, self.heading('Action items, by person'))
        ActionItemsPerson = "\n".join(ActionItemsPerson)
        return ActionItemsPerson

    def peoplePresent(self) -> str:
        M = self.M
        # People Attending
        PeoplePresent = []
        PeoplePresent.append(self.heading('People present (lines said)'))
        # sort by number of lines spoken
        for nick, count in self.iterNickCounts():
            PeoplePresent.append('* %s (%d)' % (text(nick), count))
        PeoplePresent = "\n".join(PeoplePresent)
        return PeoplePresent

    def heading(self, name: str) -> str:
        return '%s\n%s\n' % (name, '-'*len(name))

    def format(self, extension: str = None) -> str:
        """Return a plain text minutes summary."""
        M = self.M

        # Actual formatting and replacement
        repl = self.replacements()
        repl.update({'titleBlock': ('='*len(repl['pageTitle'])),
                     })

        body = []
        body.append(textwrap.dedent("""\
            %(titleBlock)s
            %(pageTitle)s
            %(titleBlock)s


            sWRAPsMeeting started by %(owner)s at %(starttime)s
            %(timeZone)s.  The full logs are available at
            %(fullLogsFullURL)seWRAPe""" % repl))
        body.append(self.meetingItems())
        body.append(textwrap.dedent("""\
            Meeting ended at %(endtime)s %(timeZone)s.""" % repl))
        body.append(self.actionItems())
        body.append(self.actionItemsPerson())
        body.append(self.peoplePresent())
        body.append(textwrap.dedent("""\
            Generated by MeetBot %(MeetBotVersion)s (%(MeetBotInfoURL)s)""" % repl))
        body = [b for b in body if b is not None]
        body = "\n\n\n\n".join(body)
        body = replaceWRAP(body)

        return body


class MediaWiki(_BaseWriter):
    """Outputs MediaWiki formats."""

    def meetingItems(self) -> str:
        M = self.M
        # Agenda items
        MeetingItems = []
        MeetingItems.append(self.heading('Meeting summary'))
        haveTopic = False
        for m in M.minutes:
            item = "* "+m.mw(M)
            if m.itemtype == "TOPIC":
                if haveTopic:
                    MeetingItems.append("")
                haveTopic = True
            else:
                if haveTopic:
                    item = "*"+item
            MeetingItems.append(item)
        MeetingItems = "\n".join(MeetingItems)
        return MeetingItems

    def actionItems(self) -> str:
        M = self.M
        # Action Items
        ActionItems = []
        for m in M.minutes:
            # The hack below is needed because of pickling problems
            if m.itemtype != "ACTION":
                continue
            # already escaped
            ActionItems.append("* %s" % mw(m.line))
        if not ActionItems:
            return None
        ActionItems.insert(0, self.heading('Action items'))
        ActionItems = "\n".join(ActionItems)
        return ActionItems

    def actionItemsPerson(self) -> str:
        M = self.M
        # Action Items, by person (This could be made lots more efficient)
        ActionItemsPerson = []
        numberAssigned = 0
        for nick in sorted(M.attendees.keys(), key=lambda x: x.lower()):
            headerPrinted = False
            for m in M.minutes:
                # The hack below is needed because of pickling problems
                if m.itemtype != "ACTION":
                    continue
                if not re.match(r'.*\b%s\b.*' % re.escape(nick), m.line, re.I):
                    continue
                if not headerPrinted:
                    ActionItemsPerson.append("* %s" % mw(nick))
                    headerPrinted = True
                ActionItemsPerson.append("** %s" % mw(m.line))
                numberAssigned += 1
                m.assigned = True
        if not ActionItemsPerson:
            return None

        # Unassigned items
        Unassigned = []
        for m in M.minutes:
            if m.itemtype != "ACTION":
                continue
            if getattr(m, 'assigned', False):
                continue
            Unassigned.append("** %s" % mw(m.line))
        if Unassigned:
            Unassigned.insert(0, "* **UNASSIGNED**")
            ActionItemsPerson.extend(Unassigned)

        ActionItemsPerson.insert(0, self.heading('Action items, by person'))
        ActionItemsPerson = "\n".join(ActionItemsPerson)
        return ActionItemsPerson

    def peoplePresent(self) -> str:
        M = self.M
        # People Attending
        PeoplePresent = []
        PeoplePresent.append(self.heading('People present (lines said)'))
        # sort by number of lines spoken
        for nick, count in self.iterNickCounts():
            PeoplePresent.append('* %s (%d)' % (mw(nick), count))
        PeoplePresent = "\n".join(PeoplePresent)
        return PeoplePresent

    def heading(self, name: str, level: int = 1) -> str:
        return '%s %s %s\n' % ('='*(level+1), name, '='*(level+1))

    body_start = textwrap.dedent("""\
            %(pageTitleHeading)s

            sWRAPsMeeting started by %(owner)s at %(starttime)s
            %(timeZone)s.  The full logs are available at
            %(fullLogsFullURL)seWRAPe""")

    def format(self, extension: str = None) -> str:
        """Return a MediaWiki formatted minutes summary."""
        M = self.M

        # Actual formatting and replacement
        repl = self.replacements()
        repl.update({'titleBlock': ('='*len(repl['pageTitle'])),
                     'pageTitleHeading': self.heading(repl['pageTitle'], level=0)
                     })

        body = []
        body.append(self.body_start % repl)
        body.append(self.meetingItems())
        body.append(textwrap.dedent("""\
            Meeting ended at %(endtime)s %(timeZone)s.""" % repl))
        body.append(self.actionItems())
        body.append(self.actionItemsPerson())
        body.append(self.peoplePresent())
        body.append(textwrap.dedent("""\
            Generated by MeetBot %(MeetBotVersion)s (%(MeetBotInfoURL)s)""" % repl))
        body = [b for b in body if b is not None]
        body = "\n\n\n\n".join(body)
        body = replaceWRAP(body)

        return body


class PmWiki(MediaWiki, object):
    def heading(self, name: str, level: int = 1) -> str:
        return '%s %s\n' % ('!'*(level+1), name)

    def replacements(self) -> dict[str, Any]:
        # repl = super(PmWiki, self).replacements(self) # fails, type checking
        repl = MediaWiki.replacements.__func__(self)
        repl['pageTitleHeading'] = self.heading(repl['pageTitle'], level=0)
        return repl


class Moin(_BaseWriter):
    """Outputs MoinMoin formats."""

    def meetingItems(self) -> str:
        M = self.M
        # Agenda items
        MeetingItems = []
        MeetingItems.append(self.heading('Meeting summary'))
        haveTopic = False
        haveSubtopic = False
        for m in M.minutes:
            item = m.moin(M)
            if m.itemtype == "TOPIC":
                if haveSubtopic:
                    haveSubtopic = False
                if haveTopic:
                    MeetingItems.append("")
                haveTopic = True
            elif m.itemtype == "SUBTOPIC":
                item = " * "+item
                haveSubtopic = True
            else:
                if not haveTopic:
                    haveTopic = True
                if haveSubtopic:
                    item = "  * "+item
                else:
                    item = " * "+item
            MeetingItems.append(item)
        MeetingItems = "\n".join(MeetingItems)
        return MeetingItems

    def fullLog(self) -> str:
        M = self.M
        Lines = []
        Lines.append(self.heading('Full log'))
        for l in M.lines:
            Lines.append(' '+l)
        Lines = "\n\n".join(Lines)
        return Lines

    def votes(self):
        M = self.M
        # Votes
        Votes = []
        # reversed to show the oldest first
        for v, (vsum, vline) in M.votes.items():
            voteLink = "%(fullLogsFullURL)s" % self.replacements()
            Votes.append(" * [[%s#%d|%s]]" % (voteLink, vline, v))
            # differentiate denied votes somehow, strikethrough perhaps?
            Votes.append("  * " + vsum)
            if M.publicVoters[v]:
                publicVoters = ', '.join(M.publicVoters[v])
                Votes.append(f"   * Voters: {publicVoters}")
        if not Votes:
            return None
        Votes.insert(0, self.heading('Vote results'))
        Votes = "\n".join(Votes)
        return Votes

    def actionItems(self) -> str:
        M = self.M
        # Action Items
        ActionItems = []
        for m in M.minutes:
            # The hack below is needed because of pickling problems
            if m.itemtype != "ACTION":
                continue
            # already escaped
            ActionItems.append(" * %s" % moin(m.line))
        if not ActionItems:
            return None
        ActionItems.insert(0, self.heading('Action items'))
        ActionItems = "\n".join(ActionItems)
        return ActionItems

    def actionItemsPerson(self) -> str:
        M = self.M
        # Action Items, by person (This could be made lots more efficient)
        ActionItemsPerson = []
        for nick in sorted(M.attendees.keys(), key=lambda x: x.lower()):
            headerPrinted = False
            for m in M.minutes:
                # The hack below is needed because of pickling problems
                if m.itemtype != "ACTION":
                    continue
                if not re.match(r'.*\b%s\b.*' % re.escape(nick), m.line, re.I):
                    continue
                if not headerPrinted:
                    ActionItemsPerson.append(" * %s" % moin(nick))
                    headerPrinted = True
                ActionItemsPerson.append("  * %s" % moin(m.line))
                m.assigned = True
        if not ActionItemsPerson:
            return None

        # Unassigned items
        Unassigned = []
        for m in M.minutes:
            if m.itemtype != "ACTION":
                continue
            if getattr(m, 'assigned', False):
                continue
            Unassigned.append("  * %s" % moin(m.line))
        if Unassigned:
            Unassigned.insert(0, " * **UNASSIGNED**")
            ActionItemsPerson.extend(Unassigned)

        ActionItemsPerson.insert(0, self.heading('Action items, by person'))
        ActionItemsPerson = "\n".join(ActionItemsPerson)
        return ActionItemsPerson

    def doneItems(self) -> str:
        M = self.M
        # Done Items
        DoneItems = []
        for m in M.minutes:
            # The hack below is needed because of pickling problems
            if m.itemtype != "DONE":
                continue
            # already escaped
            DoneItems.append(" * %s" % moin(m.line))
        if not DoneItems:
            return None
        DoneItems.insert(0, self.heading('Done items'))
        DoneItems = "\n".join(DoneItems)
        return DoneItems

    def peoplePresent(self) -> str:
        M = self.M
        # People Attending
        PeoplePresent = []
        PeoplePresent.append(self.heading('People present (lines said)'))
        # sort by number of lines spoken
        for nick, count in self.iterNickCounts():
            PeoplePresent.append(' * %s (%d)' % (moin(nick), count))
        PeoplePresent = "\n".join(PeoplePresent)
        return PeoplePresent

    def heading(self, name, level=1):
        return '%s %s %s\n' % ('='*(level+1), name, '='*(level+1))

    body_start = textwrap.dedent("""\
            == Meeting information ==

             * %(pageTitleHeading)s, started by %(owner)s, %(startdate)s at %(starttimeshort)s &mdash; %(endtimeshort)s %(timeZone)s.
             * Full logs at %(fullLogsFullURL)s""")

    def format(self, extension: str = None) -> str:
        """Return a MoinMoin formatted minutes summary."""
        M = self.M

        # Actual formatting and replacement
        repl = self.replacements()
        repl.update({'titleBlock': ('='*len(repl['pageTitle'])),
                     'pageTitleHeading': (repl['pageTitle'])
                     })

        body = []
        body.append(self.body_start % repl)
        body.append(self.meetingItems())
        body.append(self.votes())
        body.append(self.actionItemsPerson())
        body.append(self.doneItems())
        body.append(self.peoplePresent())
        if M.config.moinFullLogs:
            body.append(self.fullLog())
        body.append(textwrap.dedent("""\
            Generated by MeetBot %(MeetBotVersion)s (%(MeetBotInfoURL)s)""" % repl))
        body = [b for b in body if b is not None]
        body = "\n\n\n\n".join(body)
        body = replaceWRAP(body)

        return body


Writers = Union[HTML, HTMLfromReST, HTMLlog, TextLog, Template, ReST, MediaWiki, PmWiki, Moin]
