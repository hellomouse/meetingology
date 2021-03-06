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
from . import writers
import time
from typing import Any, Optional, Tuple, TypeVar, TYPE_CHECKING, Union
if TYPE_CHECKING:
    from .meeting import Meeting
    from _typeshed import SupportsDivMod


    _T_contra = TypeVar("_T_contra", contravariant=True)
    _T_co = TypeVar("_T_co", covariant=True)
    _TimeTuple = Tuple[int, int, int, int, int, int, int, int, int]


def inbase(i: SupportsDivMod[_T_contra@divmod, _T_co@divmod], chars: str = 'abcdefghijklmnopqrstuvwxyz', place: int = 0) -> str:
    """Converts an integer into a postfix in base 26 using ascii chars.

    This is used to make a unique postfix for ReStructured Text URL
    references, which must be unique.  (Yes, this is over-engineering,
    but keeps it short and nicely arranged, and I want practice
    writing recursive functions.)
    """
    div, mod = divmod(i, len(chars)**(place+1))
    if div == 0:
        return chars[mod]
    else:
        return inbase(div, chars=chars, place=place+1)+chars[mod]

#
# These are objects which we can add to the meeting minutes.  Mainly
# they exist to aid in HTML-formatting.
#


class _BaseItem(object):
    itemtype: Optional[str] = None
    starthtml = ''
    endhtml = ''
    startrst = ''
    endrst = ''
    starttext = ''
    endtext = ''
    startmw = ''
    endmw = ''
    startmoin = ''
    endmoin = ''

    def get_replacements(self, M: Meeting, escapewith: Union[writers.html, writers.moin, writers.mw, writers.rst, writers.text]) -> dict[str, Any]:
        replacements: dict[str, Any] = {}
        for name in dir(self):
            if name[0] == "_":
                continue
            replacements[name] = getattr(self, name)
        replacements['nick'] = escapewith(replacements['nick'])
        replacements['link'] = self.logURL(M)
        if 'line' in replacements:
            replacements['line'] = escapewith(replacements['line'])
        if 'topic' in replacements:
            replacements['topic'] = escapewith(replacements['topic'])
        if 'url' in replacements:
            replacements['url_quoteescaped'] = \
                escapewith(self.url.replace('"', "%22"))
        return replacements

    def template(self, M: Meeting, escapewith: Union[writers.html, writers.moin, writers.mw, writers.rst, writers.text]) -> dict[str, Any]:
        template: dict[str, Any] = {}
        for k, v in self.get_replacements(M, escapewith).items():
            if k not in ('itemtype', 'line', 'topic',
                         'url', 'url_quoteescaped',
                         'nick', 'time', 'link', 'anchor'):
                continue
            template[k] = v
        return template

    def makeRSTref(self, M: Meeting):
        if self.nick[-1] == '_':
            rstref = rstref_orig = "%s%s" % (self.nick, self.time)
        else:
            rstref = rstref_orig = "%s-%s" % (self.nick, self.time)
        count = 0
        while rstref in M.rst_refs:
            rstref = rstref_orig + inbase(count)
            count += 1
        link = self.logURL(M)
        M.rst_urls.append(".. _%s: %s" % (rstref, f"{link}#{self.anchor}"))
        M.rst_refs[rstref] = True
        return rstref

    @property
    def anchor(self) -> str:
        return 'l-%d' % self.linenum

    def logURL(self, M: Meeting):
        return f"{M.config.basename}.log.html"


class Topic(_BaseItem):
    itemtype = 'TOPIC'
    html_template = ("""%(starthtml)s%(topic)s%(endhtml)s """
                      """<span class="details">"""
                      """(%(nick)s, """
                      """<a href='%(link)s#%(anchor)s'>%(time)s</a>)"""
                      """</span>""")
    rst_template = """%(startrst)s%(topic)s%(endrst)s  (%(rstref)s_)"""
    text_template = """%(starttext)s%(topic)s%(endtext)s  (%(nick)s, %(time)s)"""
    mw_template = """%(startmw)s%(topic)s%(endmw)s  (%(nick)s, %(time)s)"""
    moin_template = ("""%(startmoin)s%(topic)s%(endmoin)s\n\n"""
                     """Discussion started by %(nick)s at %(time)s.\n""")

    startrst = '**'
    endrst = '**'
    startmw = "'''"
    endmw = "'''"
    starthtml = '<b class="TOPIC">'
    endhtml = '</b>'
    startmoin = '=== '
    endmoin = ' ==='

    def __init__(self, nick: str, line: str, linenum: int, time_: Union[_TimeTuple, time.struct_time]):
        self.nick = nick
        self.topic = line
        self.linenum = linenum
        self.time = time.strftime("%H:%M", time_)

    def _htmlrepl(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.html)
        repl['link'] = self.logURL(M)
        return repl

    def html(self, M: Meeting):
        return self.html_template % self._htmlrepl(M)

    def rst(self, M: Meeting):
        self.rstref = self.makeRSTref(M)
        repl = self.get_replacements(M, escapewith=writers.rst)
        if repl['topic'] == '':
            repl['topic'] = ' '
        repl['link'] = self.logURL(M)
        return self.rst_template % repl

    def text(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.text)
        repl['link'] = self.logURL(M)
        return self.text_template % repl

    def mw(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.mw)
        return self.mw_template % repl

    def moin(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.moin)
        return self.moin_template % repl


class Subtopic(Topic):
    itemtype = 'SUBTOPIC'
    moin_template = """%(startmoin)s%(topic)s%(endmoin)s  (%(nick)s, %(time)s)"""
    starthtml = '<b class="SUBTOPIC">'
    endhtml = '</b>'
    startmoin = "'''"
    endmoin = "'''"


class GenericItem(_BaseItem):
    itemtype = ''
    # html_template = ("""<i>%(itemtype)s</i>: %(starthtml)s%(line)s%(endhtml)s """
    #                  """(%(nick)s, <a href='%(link)s#%(anchor)s'>%(time)s</a>)""")
    html_template = ("""<i class="itemtype">%(itemtype)s</i>: """
                      """<span class="%(itemtype)s">"""
                      """%(starthtml)s%(line)s%(endhtml)s</span> """
                      """<span class="details">"""
                      """(%(nick)s, """
                      """<a href='%(link)s#%(anchor)s'>%(time)s</a>)"""
                      """</span>""")
    rst_template = """*%(itemtype)s*: %(startrst)s%(line)s%(endrst)s  (%(rstref)s_)"""
    text_template = """%(itemtype)s: %(starttext)s%(line)s%(endtext)s  (%(nick)s, %(time)s)"""
    mw_template = """''%(itemtype)s:'' %(startmw)s%(line)s%(endmw)s  (%(nick)s, %(time)s)"""
    moin_template = """''%(itemtype)s:'' %(startmoin)s%(line)s%(endmoin)s  (%(nick)s, %(time)s)"""

    def __init__(self, nick: str, line: str, linenum: int, time_: Union[_TimeTuple, time.struct_time]):
        self.nick = nick
        self.line = line
        self.linenum = linenum
        self.time = time.strftime("%H:%M", time_)

    def _htmlrepl(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.html)
        repl['link'] = self.logURL(M)
        return repl

    def html(self, M: Meeting):
        return self.html_template % self._htmlrepl(M)

    def rst(self, M: Meeting):
        self.rstref = self.makeRSTref(M)
        repl = self.get_replacements(M, escapewith=writers.rst)
        repl['link'] = self.logURL(M)
        return self.rst_template % repl

    def text(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.text)
        repl['link'] = self.logURL(M)
        return self.text_template % repl

    def mw(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.mw)
        return self.mw_template % repl

    def moin(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.moin)
        return self.moin_template % repl


class Info(GenericItem):
    itemtype = 'INFO'
    html_template = ("""<span class="%(itemtype)s">"""
                      """%(starthtml)s%(line)s%(endhtml)s</span> """
                      """<span class="details">"""
                      """(%(nick)s, """
                      """<a href='%(link)s#%(anchor)s'>%(time)s</a>)"""
                      """</span>""")
    rst_template = """%(startrst)s%(line)s%(endrst)s  (%(rstref)s_)"""
    text_template = """%(starttext)s%(line)s%(endtext)s  (%(nick)s, %(time)s)"""
    mw_template = """%(startmw)s%(line)s%(endmw)s  (%(nick)s, %(time)s)"""
    moin_template = """%(startmoin)s%(line)s%(endmoin)s  (%(nick)s, %(time)s)"""


class Idea(GenericItem):
    itemtype = 'IDEA'


class Agreed(GenericItem):
    itemtype = 'AGREED'


class Action(GenericItem):
    itemtype = 'ACTION'


class Help(GenericItem):
    itemtype = 'HELP'


class Done(GenericItem):
    itemtype = 'DONE'


class Vote(GenericItem):
    itemtype = 'VOTE'


class Accepted(GenericItem):
    itemtype = 'ACCEPTED'
    starthtml = '<span class="text-success">'
    endhtml = '</span>'


class Rejected(GenericItem):
    itemtype = 'REJECTED'
    starthtml = '<span class="text-danger">'
    endhtml = '</span>'


class Link(_BaseItem):
    itemtype = 'LINK'
    # html_template = ("""<i>%(itemtype)s</i>: %(starthtml)s<a href="%(url)s">%(url_readable)s</a> %(line)s%(endhtml)s """
    #                  """(%(nick)s, <a href='%(link)s#%(anchor)s'>%(time)s</a>)""")
    # html_template = ("""<i>%(itemtype)s</i>: %(starthtml)s<a href="%(url)s">%(url_readable)s</a> %(line)s%(endhtml)s """
    #                  """(<a href='%(link)s#%(anchor)s'>%(nick)s</a>, %(time)s)""")
    html_template = ("""%(starthtml)s<a href="%(url)s">%(url_readable)s</a> %(line)s%(endhtml)s """
                      """<span class="details">"""
                      """(%(nick)s, """
                      """<a href='%(link)s#%(anchor)s'>%(time)s</a>)"""
                      """</span>""")
    rst_template = """*%(itemtype)s*: %(startrst)s%(url)s %(line)s%(endrst)s  (%(rstref)s_)"""
    text_template = """%(itemtype)s: %(starttext)s%(url)s %(line)s%(endtext)s  (%(nick)s, %(time)s)"""
    mw_template = """''%(itemtype)s:'' %(startmw)s%(url)s %(line)s%(endmw)s  (%(nick)s, %(time)s)"""
    moin_template = """''%(itemtype)s:'' %(startmoin)s%(url)s %(line)s%(endmoin)s  (%(nick)s, %(time)s)"""

    def __init__(self, nick: str, line: str, linenum: int, time_: Union[_TimeTuple, time.struct_time]):
        self.nick = nick
        self.linenum = linenum
        self.time = time.strftime("%H:%M", time_)
        self.url, self.line = (line+' ').split(' ', 1)
        # URL sanitization
        self.url_readable = self.url  # readable line version
        self.line = self.line.rstrip()

    def _htmlrepl(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.html)
        # special: replace doublequote only for the URL.
        repl['url'] = writers.html(self.url.replace('"', "%22"))
        repl['url_readable'] = writers.html(self.url)
        repl['link'] = self.logURL(M)
        return repl

    def html(self, M: Meeting):
        return self.html_template % self._htmlrepl(M)

    def rst(self, M: Meeting):
        self.rstref = self.makeRSTref(M)
        repl = self.get_replacements(M, escapewith=writers.rst)
        repl['link'] = self.logURL(M)
        #repl['url'] = writers.rst(self.url)
        return self.rst_template % repl

    def text(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.text)
        repl['link'] = self.logURL(M)
        return self.text_template % repl

    def mw(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.mw)
        return self.mw_template % repl

    def moin(self, M: Meeting):
        repl = self.get_replacements(M, escapewith=writers.moin)
        return self.moin_template % repl
