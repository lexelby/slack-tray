#!/usr/bin/env python

import sys
import os
import time
from slackclient import SlackClient
from pprint import pprint


def main():
    if len(sys.argv) != 2:
        return "usage: %s <API key>" % sys.argv[0]

    client = SlackClient(sys.argv[1])
    client.rtm_connect()

    while True:
        for message in client.rtm_read():
            print time.time()
            pprint(message)
            print
        time.sleep(0.2)


if __name__ == '__main__':
    sys.exit(main())
