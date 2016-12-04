"""Handlers and dispatchers for IRC hooks live in this module.

Most of these hooks fire off specific events, which can be listened to
by code that wants to operate on these events. The events are explained
further in the relevant hook functions.

"""

from src.decorators import event_listener, hook
from src.context import Features
from src.events import Event
from src.logger import plog

from src import channels, users, settings as var

### WHO/WHOX responses handling

@hook("whoreply")
def who_reply(cli, bot_server, bot_nick, chan, ident, host, server, nick, status, hopcount_gecos):
    """Handle WHO replies for servers without WHOX support.

    Ordering and meaning of arguments for a bare WHO response:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel the request was made on
    4 - The ident of the user in this reply
    5 - The hostname of the user in this reply
    6 - The server the user in this reply is on
    7 - The nickname of the user in this reply
    8 - The status (H = Not away, G = Away, * = IRC operator, @ = Opped in the channel in 4, + = Voiced in the channel in 4)
    9 - The hop count and realname (gecos)

    This fires off the "who_result" event, and dispatches it with three
    arguments, the game state namespace, a Channel, and a User. Less
    important attributes can be accessed via the event.params namespace.

    """

    hop, realname = hopcount_gecos.split(None, 1)
    hop = int(hop)
    # We throw away the information about the operness of the user, but we probably don't need to care about that
    # We also don't directly pass which modes they have, since that's already on the channel/user
    is_away = ("G" in status)

    modes = {Features["PREFIX"].get(s) for s in status} - {None}

    user = users._add(cli, nick=nick, ident=ident, host=host, realname=realname) # FIXME
    ch = channels.add(chan, cli)

    if ch not in user.channels:
        user.channels[ch] = modes
        ch.users.add(user)
        for mode in modes:
            if mode not in ch.modes:
                ch.modes[mode] = set()
            ch.modes[mode].add(user)

    event = Event("who_result", {}, away=is_away, data=0, ip_address=None, server=server, hop_count=hop, idle_time=None, extended_who=False)
    event.dispatch(var, ch, user)

    if ch is channels.Main and not users.exists(nick): # FIXME
        users.add(nick, ident=ident, host=host, account="*", inchan=True, modes=modes, moded=set())

@hook("whospcrpl")
def extended_who_reply(cli, bot_server, bot_nick, data, chan, ident, ip_address, host, server, nick, status, hop, idle, account, realname):
    """Handle WHOX responses for servers that support it.

    An extended WHO (WHOX) is caracterised by a second parameter to the request
    That parameter must be '%' followed by at least one of 'tcuihsnfdlar'
    If the 't' specifier is present, the specifiers must be followed by a comma and at most 3 bytes
    This is the ordering if all parameters are present, but not all of them are required
    If a parameter depends on a specifier, it will be stated at the front
    If a specifier is not given, the parameter will be omitted in the reply

    Ordering and meaning of arguments for an extended WHO (WHOX) response:

    0  -   - The IRCClient instance (like everywhere else)
    1  -   - The server the requester (i.e. the bot) is on
    2  -   - The nickname of the requester (i.e. the bot)
    3  - t - The data sent alongside the request
    4  - c - The channel the request was made on
    5  - u - The ident of the user in this reply
    6  - i - The IP address of the user in this reply
    7  - h - The hostname of the user in this reply
    8  - s - The server the user in this reply is on
    9  - n - The nickname of the user in this reply
    10 - f - Status (H = Not away, G = Away, * = IRC operator, @ = Opped in the channel in 5, + = Voiced in the channel in 5)
    11 - d - The hop count
    12 - l - The idle time (or 0 for users on other servers)
    13 - a - The services account name (or 0 if none/not logged in)
    14 - r - The realname (gecos)

    This fires off the "who_result" event, and dispatches it with three
    arguments, the game state namespace, a Channel, and a User. Less
    important attributes can be accessed via the event.params namespace.

    """

    if account == "0":
        account = None

    hop = int(hop)
    idle = int(idle)
    is_away = ("G" in status)

    data = int.from_bytes(data.encode(Features["CHARSET"]), "little")

    modes = {Features["PREFIX"].get(s) for s in status} - {None}

    user = users._add(cli, nick=nick, ident=ident, host=host, realname=realname, account=account) # FIXME
    ch = channels.add(chan, cli)

    if ch not in user.channels:
        user.channels[ch] = modes
        ch.users.add(user)
        for mode in modes:
            if mode not in ch.modes:
                ch.modes[mode] = set()
            ch.modes[mode].add(user)

    event = Event("who_result", {}, away=is_away, data=data, ip_address=ip_address, server=server, hop_count=hop, idle_time=idle, extended_who=True)
    event.dispatch(var, ch, user)

    if ch is channels.Main and not users.exists(nick): # FIXME
        users.add(nick, ident=ident, host=host, account=account, inchan=True, modes=modes, moded=set())

@hook("endofwho")
def end_who(cli, bot_server, bot_nick, target, rest):
    """Handle the end of WHO/WHOX responses from the server.

    Ordering and meaning of arguments for the end of a WHO/WHOX request:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The target the request was made against
    4 - A string containing some information; traditionally "End of /WHO list."

    This fires off the "who_end" event, and dispatches it with two
    arguments: The game state namespace and a str of the request that
    was originally sent.

    """

    try:
        chan = channels.get(target)
    except KeyError:
        pass
    else:
        if chan._pending is not None:
            for name, params, args in chan._pending:
                Event(name, params).dispatch(*args)
            chan._pending = None

    Event("who_end", {}).dispatch(var, target)

### Server PING handling

@hook("ping")
def on_ping(cli, prefix, server):
    """Send out PONG replies to the server's PING requests.

    Ordering and meaning of arguments for a PING request:

    0 - The IRCClient instance (like everywhere else)
    1 - Nothing (always None)
    2 - The server which sent out the request

    """

    with cli:
        cli.send("PONG", server)

### Fetch and store server information

@hook("featurelist")
def get_features(cli, rawnick, *features):
    """Fetch and store the IRC server features.

    Ordering and meaning of arguments for a feature listing:

    0 - The IRCClient instance(like everywhere else)
    1 - The raw nick (nick!ident@host) of the requester (i.e. the bot)
    * - A variable number of arguments, one per available feature

    """

    for feature in features:
        if "=" in feature:
            name, data = feature.split("=")
            if ":" in data:
                Features[name] = {}
                for param in data.split(","):
                    param, value = param.split(":")
                    if param.isupper():
                        settings = [param]
                    else:
                        settings = param

                    for setting in settings:
                        res = value
                        if res.isdigit():
                            res = int(res)
                        elif not res:
                            res = None
                        Features[name][setting] = res

            elif "(" in data and ")" in data:
                gen = (x for y in data.split("(") for x in y.split(")") if x)
                # Reverse the order
                value = next(gen)
                Features[name] = dict(zip(next(gen), value))

            elif "," in data:
                Features[name] = data.split(",")

            else:
                if data.isdigit():
                    data = int(data)
                elif not data.isalnum() and "." not in data:
                    data = frozenset(data)
                Features[name] = data

        else:
            Features[feature] = None

### Channel and user MODE handling

@hook("channelmodeis")
def current_modes(cli, server, bot_nick, chan, mode, *targets):
    """Update the channel modes with the existing ones.

    Ordering and meaning of arguments for a bare MODE response:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel holding the modes
    4 - The modes of the channel
    * - The targets to the modes (if any)

    """

    ch = channels.add(chan, cli)
    ch.update_modes(server, mode, targets)

@hook("channelcreate")
def chan_created(cli, server, bot_nick, chan, timestamp):
    """Update the channel timestamp with the server's information.

    Ordering and meaning of arguments for a bare MODE response end:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel in question
    4 - The UNIX timestamp of when the channel was created

    We probably don't need to care about this at all, but it doesn't
    hurt to keep it around. If we ever need it, it will be there.

    """

    channels.add(chan, cli).timestamp = int(timestamp)

@hook("mode")
def mode_change(cli, rawnick, chan, mode, *targets):
    """Update the channel and user modes whenever a mode change occurs.

    Ordering and meaning of arguments for a MODE change:

    0 - The IRCClient instance (like everywhere else)
    1 - The raw nick of the mode setter/actor
    2 - The channel (target) of the mode change
    3 - The mode changes
    * - The targets of the modes (if any)

    This takes care of properly updating all relevant users and the
    channel modes to make sure we remain internally consistent.

    """

    actor = users._add(cli, nick=rawnick) # FIXME
    if chan == users.Bot.nick: # we only see user modes set to ourselves
        users.Bot.modes.update(mode)
        return

    target = channels.add(chan, cli)
    target.queue("mode_change", {"mode": mode, "targets": targets}, (var, actor, target))

@event_listener("mode_change", 0) # This should fire before anything else!
def apply_mode_changes(evt, var, actor, target):
    """Apply all mode changes before any other event."""

    target.update_modes(actor, evt.data.pop("mode"), evt.data.pop("targets"))

### List modes handling (bans, quiets, ban and invite exempts)

def handle_listmode(cli, chan, mode, target, setter, timestamp):
    """Handle and store list modes."""

    ch = channels.add(chan, cli)
    if mode not in ch.modes:
        ch.modes[mode] = {}
    ch.modes[mode][target] = (setter, int(timestamp))

@hook("banlist")
def check_banlist(cli, server, bot_nick, chan, target, setter, timestamp):
    """Update the channel ban list with the current one.

    Ordering and meaning of arguments for the ban listing:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel holding the ban list
    4 - The target of the ban
    5 - The setter of the ban
    6 - A UNIX timestamp of when the ban was set

    """

    handle_listmode(cli, chan, "b", target, setter, timestamp)

@hook("quietlist")
def check_quietlist(cli, server, bot_nick, chan, mode, target, setter, timestamp):
    """Update the channel quiet list with the current one.

    Ordering and meaning of arguments for the quiet listing:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel holding the quiet list
    4 - The quiet mode of the server (single letter)
    5 - The target of the quiet
    6 - The setter of the quiet
    7 - A UNIX timestamp of when the quiet was set

    """

    handle_listmode(cli, chan, mode, target, setter, timestamp)

@hook("exceptlist")
def check_banexemptlist(cli, server, bot_nick, chan, target, setter, timestamp):
    """Update the channel ban exempt list with the current one.

    Ordering and meaning of arguments for the ban exempt listing:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel holding the ban exempt list
    4 - The target of the ban exempt
    5 - The setter of the ban exempt
    6 - A UNIX timestamp of when the ban exempt was set

    """

    handle_listmode(cli, chan, "e", target, setter, timestamp)

@hook("invitelist")
def check_inviteexemptlist(cli, server, bot_nick, chan, target, setter, timestamp):
    """Update the channel invite exempt list with the current one.

    Ordering and meaning of arguments for the invite exempt listing:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel holding the invite exempt list
    4 - The target of the invite exempt
    5 - The setter of the invite exempt
    6 - A UNIX timestamp of when the invite exempt was set

    """

    handle_listmode(cli, chan, "I", target, setter, timestamp)

def handle_endlistmode(cli, chan, mode):
    """Handle the end of a list mode listing."""

    ch = channels.add(chan, cli)
    ch.queue("end_listmode", {}, (var, ch, mode))

@hook("endofbanlist")
def end_banlist(cli, server, bot_nick, chan, message):
    """Handle the end of the ban list.

    Ordering and meaning of arguments for the end of ban list:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel holding the ban list
    4 - A string containing some information; traditionally "End of Channel Ban List."

    """

    handle_endlistmode(cli, chan, "b")

@hook("quietlistend")
def end_quietlist(cli, server, bot_nick, chan, mode, message):
    """Handle the end of the quiet listing.

    Ordering and meaning of arguments for the end of quiet list:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel holding the quiet list
    4 - The quiet mode of the server (single letter)
    5 - A string containing some information; traditionally "End of Channel Quiet List."

    """

    handle_endlistmode(cli, chan, mode)

@hook("endofexceptlist")
def end_banexemptlist(cli, server, bot_nick, chan, message):
    """Handle the end of the ban exempt list.

    Ordering and meaning of arguments for the end of ban exempt list:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel holding the ban exempt list
    4 - A string containing some information; traditionally "End of Channel Exception List."

    """

    handle_endlistmode(cli, chan, "e")

@hook("endofinvitelist")
def end_inviteexemptlist(cli, server, bot_nick, chan, message):
    """Handle the end of the invite exempt list.

    Ordering and meaning of arguments for the end of invite exempt list:

    0 - The IRCClient instance (like everywhere else)
    1 - The server the requester (i.e. the bot) is on
    2 - The nickname of the requester (i.e. the bot)
    3 - The channel holding the invite exempt list
    4 - A string containing some information; traditionally "End of Channel Invite List."

    """

    handle_endlistmode(cli, chan, "I")

### NICK handling

@hook("nick")
def on_nick_change(cli, old_nick, nick):
    """Handle a user changing nicks, which may be the bot itself.

    Ordering and meaning of arguments for a NICK change:

    0 - The IRCClient instance (like everywhere else)
    1 - The old nickname the user changed from
    2 - The new nickname the user changed to

    """

    user = users._get(old_nick) # FIXME
    user.nick = nick

    Event("nick_change", {}).dispatch(var, user, old_nick)

### ACCOUNT handling

@hook("account")
def on_account_change(cli, rawnick, account):
    """Handle a user changing accounts, if enabled.

    Ordering and meaning of arguments for an ACCOUNT change:

    0 - The IRCClient instance (like everywhere else)
    1 - The raw nick (nick!ident@host) of the user changing accounts
    2 - The account the user changed to

    We don't see our own account changes, so be careful!

    """

    user = users._add(cli, nick=rawnick) # FIXME
    user.account = account # We don't pass it to add(), since we want to grab the existing one (if any)

    Event("account_change", {}).dispatch(var, user)

### JOIN handling

@hook("join")
def join_chan(cli, rawnick, chan, account=None, realname=None):
    """Handle a user joining a channel, which may be the bot itself.

    Ordering and meaning of arguments for a channel JOIN:

    0 - The IRCClient instance (like everywhere else)
    1 - The raw nick (nick!ident@host) of the user joining the channel
    2 - The channel the user joined

    The following two arguments are optional and only present if the
    server supports the extended-join capability (we will have requested
    it when we connected if it was supported):

    3 - The account the user is identified to, or "*" if none
    4 - The realname (gecos) of the user, or "" if none

    """

    if account == "*":
        account = None

    if realname == "":
        realname = None

    ch = channels.add(chan, cli)
    ch.state = channels._States.Joined

    user = users._add(cli, nick=rawnick, realname=realname, account=account) # FIXME
    ch.users.add(user)
    user.channels[ch] = set()

    if user is users.Bot:
        ch.mode()
        ch.mode(Features["CHANMODES"][0])
        ch.who()

    Event("chan_join", {}).dispatch(var, ch, user)

### PART handling

@hook("part")
def part_chan(cli, rawnick, chan, reason=""):
    """Handle a user leaving a channel, which may be the bot itself.

    Ordering and meaning of arguments for a channel PART:

    0 - The IRCClient instance (like everywhere else)
    1 - The raw nick (nick!ident@host) of the user leaving the channel
    2 - The channel being left

    The following argument may or may not be present:

    3 - The reason the user gave for parting (if any)

    """

    ch = channels.add(chan, cli)
    user = users._add(cli, nick=rawnick) # FIXME

    if user is users.Bot: # oh snap! we're no longer in the channel!
        ch._clear()
    else:
        ch.remove_user(user)

    Event("chan_part", {}).dispatch(var, ch, user, reason)

### KICK handling

@hook("kick")
def kicked_from_chan(cli, rawnick, chan, target, reason):
    """Handle a user being kicked from a channel.

    Ordering and meaning of arguments for a channel KICK:

    0 - The IRCClient instance (like everywhere else)
    1 - The raw nick (nick!ident@host) of the user performing the kick
    2 - The channel the kick was performed on
    3 - The target of the kick
    4 - The reason given for the kick (always present)

    """

    ch = channels.add(chan, cli)
    actor = users._add(cli, nick=rawnick) # FIXME
    user = users._add(cli, nick=target) # FIXME

    if user is users.Bot:
        ch._clear()
    else:
        ch.remove_user(user)

    Event("chan_kick", {}).dispatch(var, ch, actor, user, reason)

### QUIT handling

def quit(context, message=""):
    """Quit the bot from IRC."""

    cli = context.client

    if cli is None:
        plog("Tried to QUIT but everything was being torn down.")
        return

    with cli:
        cli.send("QUIT :{0}".format(message))

@hook("quit")
def on_quit(cli, rawnick, reason):
    """Handle a user quitting the IRC server.

    Ordering and meaning of arguments for a server QUIT:

    0 - The IRCClient instance (like everywhere else)
    1 - The raw nick (nick!ident@host) of the user quitting
    2 - The reason for the quit (always present)

    This fires off an event, after removing the user from all of their
    channels. If the user is not in a game, the event will hold the
    last reference for the user, and then it will be destroyed. If the
    user is playing, the game state will hold strong references to it,
    ensuring it's not deleted.

    """

    user = users._add(cli, nick=rawnick) # FIXME

    for chan in set(user.channels):
        if user is users.Bot:
            chan._clear()
        else:
            chan.remove_user(user)

    Event("server_quit", {}).dispatch(var, user, reason)

# vim: set sw=4 expandtab:
