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

from io import TextIOWrapper
from typing import Any, Callable, Optional, Union
from . import __version__
import os
import sys
import re
import time
import stat
from supybot import utils, log as supylog

from importlib import reload
from . import config
from . import writers
from .writers import Writers
from . import items

reload(items)

Items = Union[items.Accepted, items.Action, items.Agreed, items.Done, items.GenericItem, items.Help, items.Idea, items.Link, items.Rejected, items.Subtopic, items.Topic, items.Vote]


class MeetingCommands(object):
    # Command definitions
    # generic parameters to these functions:
    #  nick=
    #  line=    <the payload of the line>
    #  linenum= <the line number, 1-based index (for logfile)>
    #  time_=   <time it was said>
    # Commands for chairs
    def do_startmeeting(self, nick: str, line, time_, **kwargs):
        """Begin a meeting."""
        # In case of replay
        if not self.owner:
            self.owner = nick
        if not getattr(self, "starttime", None):
            self.starttime = time_
        repl = self.replacements()
        message = self.config.startMeetingMessage % repl
        for messageline in message.split('\n'):
            self.reply(messageline)
        self.do_private_commands(self.owner)
        for chair in self.chairs:
            self.do_private_commands(chair)
        self.do_commands()
        if line:
            self.do_meetingtopic(nick=nick, line=line, time_=time_, **kwargs)

    def do_endmeeting(self, nick: str, line, time_, **kwargs):
        """End the meeting."""
        if not self.isChair(nick):
            return
        # Close any open votes
        if self.activeVote:
            endVoteKwargs = {"linenum": kwargs.get("linenum", "0"),
                             "time_": time.localtime()}
            self.do_endvote(nick=nick, line=line, **endVoteKwargs)
        self.topic(self.oldtopic)
        self.endtime = time_
        self._meetingIsOver = True
        self.endmeeting()

    def do_abortmeeting(self, nick: str, line, time_, **kwargs):
        """Abort the meeting."""
        pass

    def do_replay(self, line, **kwargs):
        """Begin a replay."""
        pass

    def do_topic(self, nick: str, line: str, **kwargs):
        """Set a new topic in the channel."""
        if not self.isChair(nick):
            return
        self.currenttopic = line
        m = items.Topic(nick=nick, line=line, **kwargs)
        self.additem(m)
        self.settopic()

    def do_subtopic(self, nick: str, **kwargs):
        """This is like a topic but less so."""
        if not self.isChair(nick):
            return
        m = items.Subtopic(nick=nick, **kwargs)
        self.additem(m)
    do_progress = do_subtopic

    def do_meetingtopic(self, nick: str, line, **kwargs):
        """Set a meeting topic (included in all topics)."""
        if not self.isChair(nick):
            return
        if not line or line.lower() in ('none', 'unset'):
            self._meetingTopic = None
        else:
            self._meetingTopic = line
        self.settopic()

    def do_save(self, nick: str, time_, **kwargs):
        """Save the meeting logs by force."""
        if not self.isChair(nick):
            return
        self.endtime = time_
        self.config.save()

    def do_done(self, nick: str, **kwargs):
        """Add done item to the minutes - chairs only."""
        if not self.isChair(nick):
            return
        m = items.Done(nick=nick, **kwargs)
        self.additem(m)
        if self.config.beNoisy:
            self.reply(f"DONE: {m.line}")

    def do_agreed(self, nick: str, **kwargs):
        """Add agreement to the minutes - chairs only."""
        if not self.isChair(nick):
            return
        m = items.Agreed(nick=nick, **kwargs)
        self.additem(m)
        if self.config.beNoisy:
            self.reply(f"AGREED: {m.line}")
    do_agree = do_agreed

    def do_accepted(self, nick: str, **kwargs):
        """Add agreement to the minutes - chairs only."""
        if not self.isChair(nick):
            return
        m = items.Accepted(nick=nick, **kwargs)
        self.additem(m)
        if self.config.beNoisy:
            self.reply(f"ACCEPTED: {m.line}")
    do_accept = do_accepted

    def do_rejected(self, nick: str, **kwargs):
        """Add agreement to the minutes - chairs only."""
        if not self.isChair(nick):
            return
        m = items.Rejected(nick=nick, **kwargs)
        self.additem(m)
        if self.config.beNoisy:
            self.reply(f"REJECTED: {m.line}")
    do_reject = do_rejected

    def do_chair(self, nick: str, line: str, **kwargs):
        """Add a chair to the meeting."""
        if not self.isChair(nick):
            return
        for chair in re.split('[, ]+', line):
            if not chair:
                continue
            if chair not in self.chairs:
                if self._channelNicks and chair not in self._channelNicks():
                    self.reply("Warning: '%s' not in channel" % chair)
                self.addnick(chair, lines=0)
                self.chairs[chair] = True
                self.do_private_commands(chair)
        current_chairs = ', '.join(
            sorted(set(list(self.chairs.keys()) + [self.owner])))
        self.reply(f"Current chairs: {current_chairs}")

    def do_unchair(self, nick: str, line: str, **kwargs):
        """Remove a chair from the meeting (founder cannot be removed)."""
        if not self.isChair(nick):
            return
        for chair in re.split('[, ]+', line):
            if not chair:
                continue
            if chair in self.chairs:
                del self.chairs[chair]
        current_chairs = ', '.join(
            sorted(set(list(self.chairs.keys()) + [self.owner])))
        self.reply(f"Current chairs: {current_chairs}")

    def do_undo(self, nick: str, **kwargs):
        """Remove the last item from the minutes."""
        if not self.isChair(nick):
            return
        if not self.minutes:
            return
        self.reply("Removing item from minutes: %s" %
                   self.minutes[-1].itemtype)
        del self.minutes[-1]

    def do_restrictlogs(self, nick: str, **kwargs):
        """When saved, remove permissions from the files."""
        if not self.isChair(nick):
            return
        self._restrictlogs = True
        self.reply("Restricting permissions on minutes: -%s on next #save" %
                   oct(self.config.RestrictPerm))

    def do_lurk(self, nick: str, **kwargs):
        """Don't interact in the channel."""
        if not self.isChair(nick):
            return
        self._lurk = True

    def do_unlurk(self, nick: str, **kwargs):
        """Do interact in the channel."""
        if not self.isChair(nick):
            return
        self._lurk = False

    def do_meetingname(self, nick: str, line: str, **kwargs):
        """Set the variable (meetingname) which can be used in save.

        If this isn't set, it defaults to the channel name."""
        if not self.isChair(nick):
            return
        meetingname = "_".join(line.lower().split())
        self._meetingname = meetingname
        self.reply(f"Meeting name set to: {meetingname}")

    def do_vote(self, nick: str, line: str, **kwargs):
        """Start a voting process."""
        if not self.isChair(nick):
            return
        if self.activeVote:
            self.reply(f"Voting still open on: {self.activeVote}")
            return
        self.activeVote = line
        self.currentVote = {}
        self.publicVoters[self.activeVote] = []
        # Need the line number for linking to the html output
        self.currentVoteStartLine = len(self.lines)
        # need to set up a structure to hold vote results
        # people can vote by saying +1, -1 or +0
        # if voters have been specified then only they can vote
        # there can be multiple votes called in a meeting
        self.reply(f"Please vote on: {self.activeVote}")
        self.reply(("Public votes can be registered by saying +1, -1 or +0 in channel "
                    "(for private voting, private message me with 'vote +1|-1|+0 #channelname')"))

    def do_votesrequired(self, nick: str, line: str, **kwargs):
        """Set the number of votes required to pass a motion -
        useful for council votes where 3 of 5 people need to +1 for example."""
        if not self.isChair(nick):
            return
        try:
            self.votesrequired = int(line)
        except ValueError:
            self.votesrequired = 0
        self.reply("Votes now need %d to be passed" % self.votesrequired)

    def do_endvote(self, nick: str, line: str, **kwargs):
        """This vote is over, record the results."""
        if not self.isChair(nick):
            return
        if not self.activeVote:
            self.reply("No vote in progress")
            return

        self.reply(f"Voting ended on: {self.activeVote}")
        # should probably just store the summary of the results
        vfor = 0
        vagainst = 0
        vabstain = 0
        for v in self.currentVote.values():
            if re.match(r'\+1\b', v):
                vfor += 1
            elif re.match(r'-1\b', v):
                vagainst += 1
            elif re.match(r'[+-]?0\b', v):
                vabstain += 1

        self.reply("Votes for: %d, Votes against: %d, Abstentions: %d" %
                   (vfor, vagainst, vabstain))
        if vfor - vagainst >= self.votesrequired:
            self.reply("Motion carried")
            voteResult = "Carried"
            motion = "Motion carried"
        elif vfor - vagainst < self.votesrequired:
            self.reply("Motion denied")
            voteResult = "Denied"
            motion = "Motion denied"
        elif not self.votesrequired:
            self.reply("Deadlock, casting vote may be used")
            voteResult = "Deadlock"
            motion = "Motion deadlocked"
        # store the results
        voteSummary = "%s (For: %d, Against: %d, Abstained: %d)" % (
            motion, vfor, vagainst, vabstain)
        self.votes[self.activeVote] = (voteSummary, self.currentVoteStartLine)

        """Add informational item to the minutes."""
        voteResultLog = "%s (%s)" % (self.activeVote, voteResult)
        m = items.Vote(nick=nick, line=voteResultLog, **kwargs)
        self.additem(m)

        # allow another vote to be called
        self.activeVote = ""
        self.currentVote = {}
        self.currentVoteStartLine = 0

    def do_voters(self, nick: str, line: str, **kwargs):
        if not self.isChair(nick):
            return
        """Provide a list of authorised voters."""
        # possibly should provide a means to change voters to everyone
        for voter in re.split('[, ]+', line):
            if not voter:
                continue
            if voter in ('everyone', 'everybody', 'all'):
                # clear the voter list
                self.voters = {}
                self.reply("Everyone can now vote")
                return
            if voter not in self.voters:
                if self._channelNicks and voter not in self._channelNicks():
                    self.reply("Warning: '%s' not in channel" % voter)
                self.addnick(voter, lines=0)
                self.voters[voter] = True
        current_voters = sorted(set(list(self.voters.keys()) + [self.owner]))
        self.reply(f"Current voters: {', '.join(current_voters)}")

    def do_private_commands(self, nick: str, **kwargs):
        commands = sorted(["#"+x[3:] for x in dir(self) if x[:3] == "do_"])
        message = f"Available commands: {', '.join(commands)}"
        self.privateReply(nick, message)

    # Commands for anyone
    def do_action(self, **kwargs):
        """Add action item to the minutes.

        The line is searched for nicks, and a per-person action item
        list is compiled after the meeting.  Only nicks which have
        been seen during the meeting will have an action item list
        made for them, but you can use the #nick command to cause a
        nick to be seen."""
        m = items.Action(**kwargs)
        self.additem(m)
        if self.config.beNoisy:
            self.reply(f"ACTION: {m.line}")

    def do_info(self, **kwargs):
        """Add informational item to the minutes."""
        m = items.Info(**kwargs)
        self.additem(m)
        if self.config.beNoisy:
            self.reply(f"INFO: {m.line}")

    def do_idea(self, **kwargs):
        """Add informational item to the minutes."""
        m = items.Idea(**kwargs)
        self.additem(m)
        if self.config.beNoisy:
            self.reply(f"IDEA: {m.line}")

    def do_help(self, **kwargs):
        """Add call for help to the minutes."""
        m = items.Help(**kwargs)
        self.additem(m)
        if self.config.beNoisy:
            self.reply(f"HELP: {m.line}")
    do_halp = do_help

    def do_nick(self, nick: str, line: str, **kwargs):
        """Make meetbot aware of a nick which hasn't said anything.

        To see where this can be used, see the #action command."""
        nicks = re.split('[, ]+', line)
        for nick in nicks:
            if not nick:
                continue
            self.addnick(nick, lines=0)

    def do_link(self, **kwargs):
        """Add informational item to the minutes."""
        m = items.Link(**kwargs)
        self.additem(m)
        if self.config.beNoisy:
            self.reply(f"URI ADDED: {m.line}")

    def do_commands(self, **kwargs):
        commands = sorted(
            ["action", "info", "idea", "nick", "link", "commands"])
        self.reply(f"Available commands: {', '.join(commands)}")


class Meeting(MeetingCommands, object):
    _lurk = False
    _restrictlogs = False

    def __init__(self, channel: str, owner: str, botIsOp: Optional[bool] = False, botNick: Optional[str] = '', oldtopic: Optional[str] = '',
                 filename: Optional[str] = None, writeRawLog: Optional[bool] = False,
                 setTopic: Optional[Callable[[str], None]] = None, sendReply: Optional[Callable[[str], None]] = None, sendPrivateReply: Optional[Callable[[str, str], None]] = None,
                 getRegistryValue: Optional[Callable[[
                     str, Optional[str], Optional[str], Optional[bool]], Any]] = None,
                 safeMode: Optional[bool] = False, channelNicks: Optional[list[str]] = None,
                 extraConfig: Optional[dict[str, Any]] = {}, network: str = 'nonetwork'):

        # Load configuration
        self.config = Config
        if config.is_supybotconfig_enabled(self.config):
            self.config = config.get_config_proxy(self.config)
        self.config = self.config(self, writeRawLog=writeRawLog, safeMode=safeMode,
                                  extraConfig=extraConfig)

        if getRegistryValue is not None:
            self._registryValue = getRegistryValue
        if sendReply is not None:
            self._sendReply = sendReply
        if sendPrivateReply is not None:
            self._sendPrivateReply = sendPrivateReply
        if setTopic is not None:
            self._setTopic = setTopic
        self.owner = owner
        self.botIsOp = botIsOp
        self.botNick = botNick
        self.channel = channel
        self.network = network
        self.currenttopic = ""
        self.oldtopic = oldtopic
        self.lines = []
        self.minutes: list[Items] = []
        self.attendees: dict[str, int] = {}
        self.chairs = {}
        self.voters = {}
        self.publicVoters = {}
        self.votes = {}
        self.votesrequired = 0
        self.activeVote = ""
        self._writeRawLog = writeRawLog
        self._meetingTopic = None
        self._meetingname = ""
        self._meetingIsOver = False
        self._channelNicks = channelNicks
        if filename:
            self._filename = filename

        # Set the timezone
        os.environ['TZ'] = self.config.timeZone
        time.tzset()

    # These commands are callbacks to manipulate the IRC protocol.
    # Set self._sendReply and self._setTopic to a callback to do these things.
    def reply(self, x: str):
        """Send a reply to the channel."""
        if hasattr(self, '_sendReply') and not self._lurk:
            self._sendReply(x)
        else:
            supylog.debug("REPLY: %s" % x)

    def privateReply(self, nick: str, x: str):
        """Send a reply to a nick."""
        if hasattr(self, '_sendPrivateReply') and not self._lurk:
            self._sendPrivateReply(nick, x)

    def topic(self, x: str):
        """Set the topic in the channel."""
        if hasattr(self, '_setTopic') and not self._lurk and self.botIsOp:
            self._setTopic(x)
        else:
            supylog.debug("TOPIC: %s" % x)

    def settopic(self):
        """The actual code to set the topic."""
        topic = ''
        if self.oldtopic:
            topic += '%s | ' % self.oldtopic
        if self._meetingTopic:
            topic += self._meetingTopic
            if "meeting" not in self._meetingTopic.lower():
                topic += ' meeting'
            topic += ' | Current topic: '
        topic += self.currenttopic
        self.topic(topic)

    def addnick(self, nick: str, lines: int = 1):
        """This person has spoken, lines=<how many lines>"""
        if nick != self.botNick:
            self.attendees[nick] = self.attendees.get(nick, 0) + lines

    def isChair(self, nick: str):
        """Is the nick a chair?"""
        return (nick == self.owner or nick in self.chairs or self.isop)

    def endmeeting(self):
        """The remaining meeting end bits."""
        self.config.save()
        repl = self.replacements()
        message = self.config.endMeetingMessage % repl
        for messageline in message.split('\n'):
            self.reply(messageline)
        for nickToPM in self.config.endMeetingNotificationList:
            self.privateReply(
                nickToPM, self.config.endMeetingNotification % repl)

    def replay(self, url: str):
        """Begin a replay."""
        self.reply("Looking for meetings at: '%s'" % url)
        htmlSource = utils.web.getUrl(url).decode('utf-8')
        self.process_meeting(content=htmlSource)

    def save(self, **kwargs):
        return self.config.save(**kwargs)

    # Primary entry point for new lines in the log
    def addline(self, nick: str, line: str, isop: bool = False, time_: time.struct_time = None):
        """This is the way to add lines to the Meeting object."""
        if not time_:
            time_ = time.localtime()
        linenum = self.addrawline(nick, line, time_)
        self.isop = isop
        # Handle any commands given in the line
        matchobj = self.config.command_RE.match(line)
        if matchobj:
            command, line = matchobj.groups('')
            command = command.lower()
            # to define new commands, define a method do_commandname
            if hasattr(self, f"do_{command}"):
                getattr(self, f"do_{command}")(nick=nick, line=line,
                                               linenum=linenum, time_=time_)
        else:
            # Detect URLs automatically
            if line.split('//')[0] in self.config.UrlProtocols:
                self.do_link(nick=nick, line=line,
                             linenum=linenum, time_=time_)
        self.save(realtime_update=True)
        if re.match(r'([+-]1|[+-]?0)\b', line):
            self.doCastVote(nick, line, time_)

    def doCastVote(self, nick: str, line: str, time_=None, private: bool = False):
        """If a vote is under way and the nick is a registered voter
        and has not already voted in this vote, add the voter name and record the vote.

        If the voter has already voted, should it reject the second vote,
        or allow them to change their vote?"""
        if not self.voters or nick in self.voters:
            if self.activeVote:
                self.currentVote[nick] = line
                if not private:
                    self.publicVoters[self.activeVote].append(nick)
                    self.reply("%s received from %s" % (line, nick))

        # if the vote was in a private message - how do we do that??
        #self.reply(line + " received from a private vote")
        # we do record the voter name in the voting structure even if private, so they can't vote twice

    def addrawline(self, nick: str, line: str, time_=None):
        """This adds a line to the log, bypassing command execution."""
        self.addnick(nick)
        line = line.strip('\x01')  # \x01 is present in ACTIONs
        # Setting a custom time is useful when replaying logs,
        # otherwise use our current time
        if not time_:
            time_ = time.localtime()

        # Handle the logging of the line
        if line[:6] == 'ACTION':
            logline = "%s * %s %s" % (time.strftime("%H:%M", time_),
                                      nick, line[7:].lstrip())
        else:
            logline = "%s <%s> %s" % (time.strftime("%H:%M", time_),
                                      nick, line)
        self.lines.append(logline)
        linenum = len(self.lines)
        return linenum

    def additem(self, m: Items):
        """Add an item to the meeting minutes list."""
        self.minutes.append(m)

    def replacements(self):
        repl = {
            'channel': self.channel,
            'network': self.network,
            'MeetBotInfoURL': self.config.MeetBotInfoURL,
            'timeZone': self.config.timeZone,
            'meeting': "Meeting",
            'starttime': "None",
            'endtime': "None",
            'owner': self.owner,
            'MeetBotVersion': __version__,
            'urlBasename': self.config.filename(url=True),
        }
        if self._meetingTopic:
            repl['meeting'] = self._meetingTopic
            if "meeting" not in self._meetingTopic.lower():
                repl['meeting'] += ' meeting'
        if getattr(self, "starttime", None):
            repl['starttime'] = time.strftime("%H:%M:%S", self.starttime)
        if getattr(self, "endtime", None):
            repl['endtime'] = time.strftime("%H:%M:%S", self.endtime)
        return repl

    def process_meeting(self, content: str, dontSave: bool = False):
        def parse_time(time_):
            try:
                return time.strptime(time_, "%H:%M")
            except ValueError:
                pass
            try:
                return time.strptime(time_, "%H:%M:%S")
            except ValueError:
                pass
        if dontSave:
            self.config.dontSave = True
        # process all lines
        for line in content.split('\n'):
            # match regular spoken lines
            m = self.config.logline_RE.match(line)
            if m:
                time_ = parse_time(m.group(1))
                nick = m.group(2)
                line = m.group(3)
                self.addline(nick, line, time_=time_)
            # match /me lines
            m = self.config.loglineAction_RE.match(line)
            if m:
                time_ = parse_time(m.group(1))
                nick = m.group(2)
                line = m.group(3)
                self.addline(nick, f"ACTION {line}", time_=time_)


class Config(object):
    #
    # Throw any overrides into meetingLocalConfig.py in this directory
    #
    # Where to store the logfiles on disk
    logFileDir = '/var/www/meetbot/'
    # The links to the logfiles are given this prefix
    logUrlPrefix = 'https://meetbot.hellomouse.net/'
    # Give the pattern to save files into here.  Use %(channel)s for
    # channel.  This will be sent through strftime for substituting the
    # times; however, for strftime codes you must use doubled percent
    # signs (%%).  This will be joined with the directories above.
    filenamePattern = '%(channel)s/%%Y/%(channel)s.%%F-%%H.%%M'
    # Where to say to go for more information about MeetBot
    MeetBotInfoURL = 'https://wiki.debian.org/MeetBot'
    # This is used with the #restrict command to remove permissions from files.
    RestrictPerm = stat.S_IRWXO | stat.S_IRWXG  # g,o perm zeroed
    # RestrictPerm = stat.S_IRWXU|stat.S_IRWXO|stat.S_IRWXG  # u,g,o perm zeroed
    # Used to detect #link
    UrlProtocols = ['http:', 'https:', 'irc:', 'ftp:', 'mailto:', 'ssh:']
    # Regular expression for parsing commands.
    command_RE = re.compile(r'^#(\w+)(?:\s+(.*?)|)\s*$')
    # Regular expressions for parsing loglines.
    logline_RE = re.compile(
        r'^\[?([0-9:]+)\]?\s*<[@%&+ ]?([^>]+)>\s*(.*?)\s*$')
    loglineAction_RE = re.compile(r'^\[?([0-9:]+)\]?\s*\*\s*(\S+)\s*(.*?)\s*$')
    # The channels which won't have date/time appended to the filename.
    specialChannels = ["#meetbot-test"]
    specialChannelFilenamePattern = '%(channel)s/%(channel)s'
    # HTML irc log highlighting style.  `pygmentize -L styles` to list.
    pygmentizeStyle = 'friendly'
    # Timezone setting.  You can use friendly names like 'US/Eastern', etc.
    # Check /usr/share/zoneinfo/ or `man timezone`; this is the content
    # of the TZ environment variable.
    timeZone = 'UTC'
    # These are the start and end meeting messages, respectively.
    # Some replacements are done before they are used, using the
    # %(name)s syntax.  Note that since one replacement is done below,
    # you have to use doubled percent signs.  Also, it gets split by
    # '\n' and each part between newlines gets said in a separate IRC
    # message.
    startMeetingMessage = ("Meeting started at %(starttime)s %(timeZone)s.  "
                           "The chair is %(owner)s.  Information about MeetBot at "
                           "%(MeetBotInfoURL)s")
    # TODO: endMeetingMessage should get filenames from the writers
    endMeetingMessage = ("Meeting ended at %(endtime)s %(timeZone)s.  "
                         "Minutes at %(urlBasename)s.html")
    endMeetingNotification = ("%(meeting)s in %(channel)s has just ended")
    endMeetingNotificationList = []

    # Should the bot talk in the channel
    beNoisy = True
    # Input/output codecs.
    input_codec = 'utf-8'
    output_codec = 'utf-8'

    # Write out select logfiles
    update_realtime = True
    # CSS configs
    cssFile_log = 'default'
    cssEmbed_log = False
    cssFile_minutes = 'default'
    cssEmbed_minutes = False
    # Include full log in MoinMoin output
    moinFullLogs = False

    # This tells which writers write out which to extensions.
    writer_map: dict[str, Writers] = {
        '.log.html': writers.HTMLlog,
        '.html': writers.HTML,
        '.rst': writers.ReST,
        '.txt': writers.Text,
        '.rst.html': writers.HTMLfromReST,
        '.moin.txt': writers.Moin,
        '.mw.txt': writers.MediaWiki,
    }

    def __init__(self, M: Meeting, writeRawLog: bool = False, safeMode: bool = False,
                 extraConfig: dict[str, Any] = {}):
        self.M = M
        self.writeRawLog = writeRawLog
        self.safeMode = safeMode
        # Update config values with anything we may have
        for k, v in extraConfig.items():
            setattr(self, k, v)

    def setWriters(self):
        self.writers: dict[str, Writers] = {}
        if self.writeRawLog:
            self.writers['.log.txt'] = writers.TextLog(self.M)
        for extension, writer in self.writer_map.items():
            self.writers[extension] = writer(self.M)

    def filename(self, url: bool = False) -> str:
        # provide a way to override the filename.  If it is
        # overridden, it must be a full path (and the URL-part may not
        # work.):
        if getattr(self.M, '_filename', None):
            return self.M._filename
        # names useful for pathname formatting.
        # Certain test channels always get the same name - don't need
        # file prolifiration for them
        if self.M.channel in self.specialChannels:
            pattern = self.specialChannelFilenamePattern
        else:
            pattern = self.filenamePattern
        channel = self.M.channel.strip('# ').lower().replace('/', '')
        network = self.M.network.strip(' ').lower().replace('/', '')
        if self.M._meetingname:
            meetingname = self.M._meetingname.replace('/', '')
        else:
            meetingname = channel
        path = pattern % {'channel': channel, 'network': network,
                          'meetingname': meetingname}
        path = time.strftime(path, self.M.starttime)
        # If we want the URL name, append URL prefix and return
        if url:
            return os.path.join(self.logUrlPrefix, path)
        path = os.path.join(self.logFileDir, path)
        # make directory if it doesn't exist...
        dirname = os.path.dirname(path)
        if not url and dirname and not os.access(dirname, os.F_OK):
            os.makedirs(dirname)
        return path

    @property
    def basename(self) -> str:
        return os.path.basename(self.M.config.filename())

    def save(self, realtime_update: bool = False):
        """Write all output files.

        If `realtime_update` is true, then this isn't a complete save,
        it will only update those writers with the realtime_update
        attribute true."""
        if realtime_update and not hasattr(self.M, 'starttime'):
            return
        rawname = self.filename()
        # We want to write the rawlog (.log.txt) first in case the
        # other methods break.  That way, we have saved enough to
        # replay.
        if not hasattr(self, 'writers'):
            self.setWriters()
        writer_names = list(self.writers.keys())
        results = {}
        if '.log.txt' in writer_names:
            writer_names.remove('.log.txt')
            writer_names.insert(0, '.log.txt')
        for extension in writer_names:
            writer = self.writers[extension]
            # Why this?  If this is a realtime (step-by-step) update,
            # then we only want to update those writers which say they
            # should be updated step-by-step.
            if (realtime_update and (not self.update_realtime or
                                     not getattr(writer, 'update_realtime', False) or
                                     getattr(self, '_filename', None))
                ):
                continue
            # Parse embedded arguments
            if '|' in extension:
                extension, args = extension.split('|', 1)
                args = args.split('|')
                args = dict([a.split('=', 1) for a in args])
            else:
                args = {}

            text = writer.format(extension, **args)
            results[extension] = text
            # If the writer returns a string or unicode object, then
            # we should write it to a filename with that extension.
            # If it doesn't, then it's assumed that the write took
            # care of writing (or publishing or emailing or wikifying)
            # it itself.
            if isinstance(text, str):
                # Have a way to override saving, so no disk files are written.
                if getattr(self, "dontSave", False):
                    continue
                self.writeToFile(text, f"{rawname}{extension}")
        return results

    def writeToFile(self, string: str, filename: str):
        """Write a given string to a file."""
        # The reason we have this method just for this is to proxy
        # through the _restrictPermissions logic.
        with open(filename, 'w') as f:
            if self.M._restrictlogs:
                self.restrictPermissions(f)
            f.write(string)

    def restrictPermissions(self, f: TextIOWrapper):
        """Remove the permissions given in the variable RestrictPerm."""
        f.flush()
        newmode = os.stat(f.name).st_mode & (~self.RestrictPerm)
        os.chmod(f.name, newmode)


# Load local configuration
try:
    from . import meetingLocalConfig
    meetingLocalConfig = reload(meetingLocalConfig)
    if hasattr(meetingLocalConfig, 'Config'):
        Config = type('Config', (meetingLocalConfig.Config, Config), {})
except ImportError:
    pass
