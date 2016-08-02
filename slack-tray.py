#!/usr/bin/env python

import sys
import os
import time
import re
import socket
from slackclient import SlackClient
from pprint import pprint
import json
from collections import defaultdict
import itertools
from threading import Thread
import gtk
import gobject
import yaml
from collections import defaultdict
import traceback

AT_HERE_RE = re.compile('<!(here|group|everyone|channel)(|[a-z]+)?>', re.I)
config = {}


# This class can be used as a decorator to cache the results of function
# calls.
class memoize(dict):
    def __init__(self, f):
        self.f = f

    def __call__(self, *args):
        try:
            return self[args]
        except TypeError:
            print "error memoizing:"
            traceback.print_exc()
            return self.f(*args)

    def __missing__(self, key):
        ret = self[key] = self.f(*key)
        return ret


class DotDict(defaultdict):
    """Allows attribute-like access.  Returns an empty DotDict when an item is
    accessed that is not in the dict."""

    def __init__(self, *args, **kwargs):
        super(DotDict, self).__init__(DotDict, *args, **kwargs)

    def __getattr__(self, attr):
        try:
            return self[attr]
        except KeyError:
            return self.__missing__(attr)


# The following magic makes yaml use DotDict instead of dict
def dotdict_constructor(loader, node):
    return DotDict(loader.construct_pairs(node))


yaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, dotdict_constructor)


def read_config(path):
    global config

    with open(path) as config_file:
        config = yaml.load(config_file)


def get_rtm_info(client):
    # Apparently the only way to get this info is to call rtm.start.
    # SlackClient doesn't return the full results from rtm_connect(),
    # so we'll call it here too.

    return client.api_call('rtm.start')


def update_starred_channels(client):
    try:
        response = client.api_call('stars.list')
        stars = response['items']
        starred_channels = [star['channel'] for star in stars if star['type'] in ('channel', 'group')]
        config.starred_channels = starred_channels
    except:
        traceback.print_exc()

    # print 'starred channels:', config.starred_channels

    return True


@memoize
def get_user_name(client, id):
    response = client.api_call("users.info", user=id)

    if response.get("ok"):
        return response['user']['name']
    else:
        return "<UNKNOWN>"


def unlistify(thing):
    # For some stupid reason server.channels.find() returns either a single item
    # or a list.  They coded it specifically to do this and now I have to code
    # around it.
    if isinstance(thing, (list, tuple)):
        return thing[0]
    else:
        return thing


@memoize
def get_channel_name(client, id):
    if not id:
        return None

    channel = client.server.channels.find(id)

    if id[0] != "D" and channel is not None:
        name = unlistify(channel).name

        if id[0] == "C":
            name = "#" + name

        return name
    else:
        if id[0] == "C":
            response = client.api_call("channels.info", channel=id)

            if response.get("ok"):
                return "#" + response["channel"]["name"]
        elif id[0] == "G":
            response = client.api_call("groups.list")

            if response.get("ok"):
                for group in response['groups']:
                    if group['id'] == id:
                        return group['name']
        elif id[0] == "D":
            response = client.api_call("im.list")

            if response.get("ok"):
                for im in response['ims']:
                    if im['id'] == id:
                        return "IM: " + get_user_name(client, im['user'])

    return "<UNKNOWN>"


def render(client, text):
    def name_getter(function):
        return lambda match: function(client, match.group(1))

    text = re.sub("<#([^>]+)>", name_getter(get_channel_name), text)
    text = re.sub("<@([^>]+)>", name_getter(get_user_name), text)

    return text

def mark_read(client, channel, timestamp):
    #print "mark_read(", client, channel, timestamp, ")"

    kwargs = dict(channel=channel, ts=timestamp)

    # Why can't you do this for me, slack?
    if channel.startswith('C'):
        client.api_call("channels.mark", **kwargs)
    elif channel.startswith('G'):
        client.api_call("groups.mark", **kwargs)
    elif channel.startswith('D'):
        client.api_call("im.mark", **kwargs)

    # Cause gobject not to reschedule this function call.
    return False

def log_ping(client, channel_name, user, message):
    # aggregate pings under "slackbot"
    #
    # as_user=false and channel=@<my username> causes message to appear under
    # "slackbot".  username=channel_name causes the channel name to appear as
    # a heading of sorts.

    print "log_ping", channel_name, user, message

    client.api_call('chat.postMessage',
        as_user=False,
        channel='@%s' % client.server.username,
        username=channel_name,
        text='%s: %s' % (user, message))

    # Cause gobject not to reschedule this function call.
    return False

def build_highlight_re(words):
    words = [re.escape(word) for word in words if word]

    return re.compile(r'(^|_|\W)(%s)(?!@)(_|\W|$)' % "|".join(words), re.I)


def shell_escape(string):
    return string.replace("'", "'\\''")


def play(sound):
    os.system("/usr/bin/paplay -n slack-tray %s" % sound)


def notify(subject, message):
    subject = shell_escape(subject)
    message = shell_escape(message)
    command = "/usr/bin/notify-send '%s' '%s'" % (subject, message)
    os.system(command)


def ping(message):
    print "PING:", message
    play(config.sounds.ping)
    notify("Slack Chat", message)


def pm(message):
    print "PM:", message
    play(config.sounds.pm)
    notify("Slack PM", message)


def email(subject, message):
    print "EMAIL:", message
    play(config.sounds.email)
    notify(subject, message)


class TrayIcon(object):
    def __init__(self):
        self.icon = gtk.StatusIcon()
        self.icon.set_visible(False)
        self.color = None

    def set_color(self, color):
        gobject.idle_add(self._set_color, color)

    def _set_color(self, color):
        if color != self.color:
            self.color = color
            self.icon.set_from_file(os.path.join(os.path.dirname(__file__), "slack_%s.png" % color))
            self.icon.set_visible(True)

        return False


class Channel(object):
    def __init__(self):
        self.last_unread = None
        self.last_highlight = None
        self.read_marker = None

    def add_unread(self, timestamp):
        self.last_unread = max(self.last_unread, timestamp)

    def add_highlight(self, timestamp):
        self.last_highlight = max(self.last_highlight, timestamp)

    def update_marker(self, timestamp):
        self.read_marker = max(self.read_marker, timestamp)

    def is_unread(self):
        return self.read_marker is not None and self.last_unread > self.read_marker

    def is_highlighted(self):
        return self.read_marker is not None and self.last_highlight > self.read_marker

    def __repr__(self):
        if self.is_highlighted():
            return "<HIGHLIGHTED>"
        elif self.is_unread():
            return "<UNREAD>"
        else:
            return "<READ>"

def mainLoop():
    if len(sys.argv) != 2:
        return "usage: %s <config file>" % sys.argv[0]

    read_config(sys.argv[1])

    client = SlackClient(config.api_key)

    info = get_rtm_info(client)
    muted_channels = info['self']['prefs']['muted_channels'].split(',')
    highlight_words = info['self']['prefs']['highlight_words'].split(',') + [info['self']['name'], "<@%s>" % info['self']['id']]
    highlight_re = build_highlight_re(highlight_words)
    no_highlight_re = build_highlight_re(config.notify.blacklist_words)

    if config.mark_unstarred_channels_as_read:
        update_starred_channels(client)
        gobject.timeout_add(60000, update_starred_channels, client)

    channels = defaultdict(Channel)

    for channel in itertools.chain(info['channels'], info['groups'], info['ims']):
        if 'last_read' in channel:
            channels[channel['id']].update_marker(channel['last_read'])

    client.rtm_connect()

    last_ping = time.time()
    last_pong = time.time()

    print "ready"

    while True:
        messages = client.rtm_read()

        if messages:
            for message in messages:
                channel = message.get('channel')
                if isinstance(channel, basestring):
                    channel_name = get_channel_name(client, channel)
                elif channel is None:
                    channel_name = None
                else:
                    print "wtf is this channel: ", type(channel), repr(channel), channel

                channel_name = get_channel_name(client, channel)
                timestamp = message.get('ts')
                mtype = message.get('type')
                msubtype = message.get('subtype')
                text = message.get('text', "")
                user = message.get('user')

                #print "rtm_debug:", message
                #print channel, channel_name

                if (mtype == 'message'
                    and msubtype in (None, "bot_message", "me_message")
                    and user is not None
                    and user != "USLACKBOT"):
                        channels[channel].add_unread(timestamp)
                        is_muted = channel in muted_channels
                        is_highlight = highlight_re.search(text) and not (config.notify.blacklist_words and no_highlight_re.search(text))
                        is_at_here = not is_muted and AT_HERE_RE.search(text)
                        is_pm = channel.startswith('D') or channel_name.startswith("mpdm-")

                        if user != info['self']['id'] and channel_name not in config.notify.blacklist_channels:
                            notification_function = None

                            if is_pm:
                                notification_function = pm
                            elif is_highlight or is_at_here:
                                if config.log_pings and channel in muted_channels:
                                    gobject.idle_add(log_ping, client, channel_name, get_user_name(client, user), render(client, text))

                                notification_function = ping

                            if notification_function:
                                channels[channel].add_highlight(timestamp)
                                notification_function("%s %s: %s" % (channel_name, get_user_name(client, user), render(client, text)))
                        if channel_name in config.mark_read_channels or is_muted:
                                # print "mark read:", channel
                                channels[channel].update_marker(timestamp)
                                gobject.idle_add(mark_read, client, channel, timestamp)
                elif (channel_name in config.notify.email_ping_channels
                      and mtype == "message" and message.get('upload')):
                        email(message['username'], message['file']['title'])
                elif mtype in ('channel_marked', 'im_marked', 'group_marked'):
                    channels[channel].update_marker(timestamp)
                elif mtype == "pong":
                    last_pong = time.time()

#            if messages:
#                for id, channel in channels.iteritems():
#                    if channel.is_unread():
#                        print get_channel_name(client, id), id, channel

            unmuted_channels = [channel for id, channel in channels.iteritems() if id not in muted_channels]

            if any(channel.is_highlighted() for channel in channels.itervalues()):
                tray_icon.set_color("red")
            elif any(channel.is_unread() for channel in unmuted_channels):
                tray_icon.set_color("yellow")
            else:
                tray_icon.set_color("green")

        try:
            if time.time() - last_ping > 30:
                client.server.ping()
                last_ping = time.time()
        except socket.error:
            last_pong = 0

        if time.time() - last_pong > 60:
            try:
                print "lost connection, reconnecting..."
                client.rtm_connect()
            except socket.error:
                # we'll end up retrying after 60 seconds with no pong
                pass

            last_pong = time.time()

        time.sleep(0.2)


def main():
    try:
        mainLoop()
    except KeyboardInterrupt:
        raise
    except:
        print >> sys.stderr, "main loop crashed!"
        traceback.print_exc()

        time.sleep(3)
        print >> sys.stderr, "restarting"
        print >> sys.stderr

        os.execv(sys.argv[0], sys.argv)

if __name__ == '__main__':
    gobject.threads_init()
    tray_icon = TrayIcon()
    Thread(target=main).start()
    try:
        gtk.main()
    except KeyboardInterrupt:
        os._exit(0)
