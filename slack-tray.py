#!/usr/bin/env python

import sys
import os
import time
import re
from slackclient import SlackClient
from pprint import pprint
import json
from collections import defaultdict
import itertools


def get_rtm_info(client):
    # Apparently the only way to do this is to call rtm.start.  SlackClient
    # doesn't return the full results from that call, so we'll call it
    # here too.

    info = json.loads(client.api_call('rtm.start'))
    return info


def build_highlight_re(words):
    words = [re.escape(word) for word in words]

    return re.compile(r'(^|_|\W)(%s)(_|\W|$)' % "|".join(words), re.I)


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
    play("/usr/share/sounds/purple/receive.wav")
    notify("Slack Chat", message)

def pm(message):
    print "pm received"
    play("/usr/share/sounds/purple/alert.wav")
    notify("Slack PM", message)



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
        return "usage: %s <API key>" % sys.argv[0]

    api_key = sys.argv[1]

    client = SlackClient(api_key)

    info = get_rtm_info(client)
    muted_channels = info['self']['prefs']['muted_channels'].split(',')
    highlight_words = info['self']['prefs']['highlight_words'].split(',') + [info['self']['name'], "<@%s>" % info['self']['id']]
    highlight_re = build_highlight_re(highlight_words)

    print highlight_re.pattern

    channels = defaultdict(Channel)

    for channel in itertools.chain(info['channels'], info['groups'], info['ims']):
        if 'last_read' in channel:
            channels[channel['id']].update_marker(channel['last_read'])

    client.rtm_connect()

    status = None

    while True:
        messages = client.rtm_read()

        for message in messages:
            channel = message.get('channel')
            timestamp = message.get('ts')
            mtype = message.get('type')
            text = message.get('text')

            if mtype == 'message':
                channels[channel].add_unread(timestamp)

                if text and highlight_re.search(text):
                    channels[channel].add_highlight(timestamp)
                    ping("%s: %s" % (client.channels.find(channel).name, text)

            elif mtype in ('channel_marked', 'im_marked', 'group_marked'):
                channels[channel].update_marker(timestamp)

        if messages:
            #print channels
            pass

        unmuted_channels = [channel for name, channel in channels.iteritems() if name not in muted_channels]

        if any(channel.is_highlighted() for channel in channels.itervalues()):
            new_status = "red"
        elif any(channel.is_unread() for channel in unmuted_channels):
            new_status = "yellow"
        else:
            new_status = "green"

        if new_status != status:
            status = new_status
            print time.time(), status

        time.sleep(0.2)


if __name__ == '__main__':
    sys.exit(main())
