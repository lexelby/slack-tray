Slack Tray
==========

This is a little python script I wrote to make my experience with Slack in Linux more enjoyable.  I wrote it because I wanted to do a few things that the slack web client can't do.  Here are a couple of use cases that motivated me:

Show a colored tray icon telling me whether I have unread messages or highlights.
---------

I think the official desktop clients might support this, but there isn't one for Linux.

Customize the sounds used for highlights and IMs.
---------

I like my sounds better.  Plus, the slack web client doesn't let you choose a separate sound for IMs.


Better desktop notifications for Linux.
---------

Uses `notify-send` from `libnotify-bin`.

Notifications for highlights in muted channels.
---------

This one's a bit quirky.  See, I'd like to maintain a presence in certain channels so that people can ping me.  For example, I want the support team to be able to tell me the site's on fire.  However, I don't want unread messages to make the channel try to get my attention in the slack web client.  I also want the channel to be listed with all of the rest of the channels I care about (starred), but I don't want it to have the same importance as the rest of them (greyed).

"Muting" and "Starring" the channel is perfect.  It lists the channel with all of the other channels I care about at the top of the list, but it greys it out.  The only problem is that if you mute a channel, the slack web client won't pop up notifications and make sound if you're pinged.  This script does that.

Always mark messages in some channels as read.
-----------

We have a channel for bots to send us messages ("disk failed on <host>", "<host> is on fire", "someone put <host> in maintenance mode", etc).  I view the stream of automated notifications in a separate little always-open window via the IRC client irssi, using Slack's IRC bridge.  Since I'm seeing these messages, I don't want/need the channel to show as unread in my main slack client.  I don't want to Mute the channel because it's one I actually care about.  This script will automatically mark any new messages in the bot channel as read.

Ignore highlights in specific channels.
-----------
We have a channel where a bot logs every single command that an administrator runs at the shell on every server.  Kind of big-brotherish, sure, but it's incredibly useful!  However, I don't want to be notified if someone mentions my name in there, because it's probably me sudoing something or editing a file in my homedir.

You're a weirdo.
=============

Yeah, I might be.  But I have good reasons for wanting every one of these features, and fortunately, Slack's awesome API gives me the ability to customize things to my heart's content.

Installing
==========

I've tested this in Linux only, but it might well work in other OSes.  Let me know!

You'll need these packages (debian/ubuntu -- no idea for RedHat and derivatives):

* libnotify-bin
* python-yaml
* python-gtk2
* [python-slackclient](https://github.com/slackhq/python-slackclient)
* pulseaudio
  * `paplay` is used for playing sound.  There may be a more universal way of doing this.

Copy `config.yaml.example` to `config.yaml` and edit it as necessary.  Then run `slack-tray.py` with the path to the config file as an argument, and it'll do its thing.
