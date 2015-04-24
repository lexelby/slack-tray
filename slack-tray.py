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


config = {}


# This class can be used as a decorator to cache the results of function
# calls.
class memoize(dict):
    def __init__(self, f):
        self.f = f

    def __call__(self, *args):
        return self[args]

    def __missing__(self, key):
        ret = self[key] = self.f(*key)
        return ret


class DotDict(defaultdict):
    """Allows attribute-like access.  Returns {} when an item is accessed that
    is not in the dict."""

    def __init__(self, *args, **kwargs):
        super(DotDict, self).__init__(dict, *args, **kwargs)

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
    # Apparently the only way to do this is to call rtm.start.  SlackClient
    # doesn't return the full results from that call, so we'll call it
    # here too.

    info = json.loads(client.api_call('rtm.start'))
    return info


@memoize
def get_user_name(client, id):
    response = json.loads(client.api_call("users.info", user=id))

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
    channel = client.server.channels.find(id)

    if id[0] != "D" and channel is not None:
        name = unlistify(channel).name

        if id[0] == "C":
            name = "#" + name

        return name
    else:
        if id[0] == "C":
            response = json.loads(client.api_call("channels.info", channel=id))

            if response.get("ok"):
                return "#" + response["channel"]["name"]
        elif id[0] == "G":
            response = json.loads(client.api_call("groups.list"))

            if response.get("ok"):
                for group in response['groups']:
                    if group['id'] == id:
                        return group['name']
        elif id[0] == "D":
            response = json.loads(client.api_call("im.list"))

            if response.get("ok"):
                for im in response['ims']:
                    if im['id'] == id:
                        return "IM: " + get_user_name(client, im['user'])

    return "<UNKNOWN>"


def mark_read(client, channel, timestamp):
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


def build_highlight_re(words):
    words = [re.escape(word) for word in words]

    return re.compile(r'(^|_|\W)(%s)(?!@)(_|\W|$)' % "|".join(words), re.I)


def shell_escape(string):
    return string.replace("'", "'\\''")


def play(sound):
    os.system("/usr/bin/paplay %s" % sound)


def notify(subject, message):
    subject = shell_escape(subject)
    message = shell_escape(message)
    command = "/usr/bin/notify-send '%s' '%s'" % (subject, message)
    os.system(command)


def ping(message):
    print "pinged"
    play(config.sounds.ping)
    notify("Slack Chat", message)


def pm(message):
    print "pm received"
    play(config.sounds.pm)
    notify("Slack PM", message)


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


def main():
    if len(sys.argv) != 2:
        return "usage: %s <config file>" % sys.argv[0]

    read_config(sys.argv[1])

    client = SlackClient(config.api_key)

    info = get_rtm_info(client)
    muted_channels = info['self']['prefs']['muted_channels'].split(',')
    highlight_words = info['self']['prefs']['highlight_words'].split(',') + [info['self']['name'], "<@%s>" % info['self']['id']]
    highlight_re = build_highlight_re(highlight_words)
    no_highlight_re = build_highlight_re(config.notify.blacklist_words)

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
                timestamp = message.get('ts')
                mtype = message.get('type')
                text = message.get('text')
                user = message.get('user')

                if mtype == 'message':
                    channels[channel].add_unread(timestamp)
                    channel_name = get_channel_name(client, channel)

                    if user != info['self']['id'] and channel_name not in config.notify.blacklist_channels:
                        notification_function = None

                        if channel[0] == 'D':
                            notification_function = pm
                        elif text and highlight_re.search(text) and not \
                                (config.notify.blacklist_words and no_highlight_re.search(text)):
                            notification_function = ping

                        if notification_function:
                            channels[channel].add_highlight(timestamp)
                            notification_function("%s: %s" % (channel_name, text))

                    if channel_name in config.mark_read_channels:
                        channels[channel].update_marker(timestamp)
                        gobject.idle_add(mark_read, client, channel, timestamp)
                elif mtype in ('channel_marked', 'im_marked', 'group_marked'):
                    channels[channel].update_marker(timestamp)
                elif mtype == "pong":
                    last_pong = time.time()

            if messages:
                # print channels
                pass

            unmuted_channels = [channel for name, channel in channels.iteritems() if name not in muted_channels]

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
            print "lost connection, reconnecting..."
            client.rtm_connect()
            last_pong = time.time()

        time.sleep(0.2)


if __name__ == '__main__':
    gobject.threads_init()
    tray_icon = TrayIcon()
    Thread(target=main).start()
    try:
        gtk.main()
    except KeyboardInterrupt:
        os._exit(0)
