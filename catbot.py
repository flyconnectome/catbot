"""
    Catbot (https://github.com/flyconnectome/catbot) is a Slack bot that interfaces with CATMAID.
    Copyright (C) 2017 Philipp Schlegel

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import matplotlib
# Switch a non-interactive, PNG-only backend. On Linux Tkinter, the default
# backend, causes trouble
matplotlib.use('AGG')

import certifi
import logging
import random
import re
import ssl as ssl_lib
import sys
import subprocess
import threading

from datetime import datetime, date, timedelta
from functools import wraps

import pymaid

import slack


def respond_error(function):
    """Run function in try context and respond with error msg if exception."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        # Execute function
        try:
            res = function(*args, **kwargs)
        except BaseException as e:
            # Now parse data
            data = kwargs.get('data', {})
            msg = data.get('text', '')

            # If this is not directed at me, ignore it
            if botconfig.AT_BOT not in msg:
                return

            # Parse remainder of message
            web_client = kwargs.get('web_client')
            channel = data.get('channel')
            user_id = data.get('user')
            user_name = user_list[user_id]

            logger.error(f'Error in command "{msg}" from user {user_name} '
                         f'({user_id}) in channel {channel}:')
            logger.error(e, exc_info=True)

            resp = "Ooops - something went wrong! Please let one of my admins" \
                   " know if this keeps happening!"
            _ = web_client.chat_postMessage(text=resp,
                                            channel=channel,
                                            as_user=True)
        # Return result
        return res
    return wrapper


class return_url(threading.Thread):
    """Class to process incoming url to neuron request."""

    def __init__(self, web_client, command, channel):
        self.command = command.lower()
        self.raw_command = command
        self.channel = channel
        self.web_client = web_client
        self.id = random.randint(1, 99999)
        threading.Thread.__init__(self)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug(f'Thread {self.id} closed')
            return None
        except Exception:
            logger.error(f'Failed to join thread for Thrad {self.id}',
                         exc_info=True)
        return None

    def run(self):
        """Return urls for a list of neurons."""
        skids = parse_neurons(self.raw_command)
        logger.debug(f'Started new thread {self.id} for command "{self.command}"')

        for s in skids:
            if not pymaid.neuron_exists(s, remote_instance=remote_instance):
                response = f"I'm sorry - the neuron #{s} does not seem to exists. Please try again."
                _ = self.web_client.chat_postMessage(channel=self.channel,
                                                     text=response,
                                                     as_user=True)
                return

        if not skids:
            response = 'Please provide neurons as `#{skid}`, `annotation="{annotation}"` ' \
                       'or `name="{name}"`! For example: `@catbot url #957684`'
        else:
            response = 'Here are URLs to the neurons you have provided!'
            skdata = pymaid.get_neuron(skids, remote_instance=remote_instance,
                                       connector_flag=0, tag_flag=0,
                                       get_history=False)

            skdata = pymaid.CatmaidNeuronList(skdata)

            for neuron in skdata:
                root = neuron.nodes[neuron.nodes.type == 'root']
                url = pymaid.url_to_coordinates(root,
                                                stack_id=5,
                                                tool='tracingtool',
                                                active_skeleton_id=neuron.skeleton_id,
                                                active_node_id=root.treenode_id.values,
                                                remote_instance=remote_instance)
                for u in url:
                    response += f'\n *#{neuron.skeleton_id}*: {u}'

        if response:
            self.web_client.chat_postMessage(channel=self.channel,
                                             text=response,
                                             as_user=True)

        return response


class return_help(threading.Thread):
    """Class to process incoming help request."""

    def __init__(self, web_client, command, channel):
        self.command = command.lower()
        self.raw_command = command
        self.channel = channel
        self.web_client = web_client
        self.id = random.randint(1, 99999)
        threading.Thread.__init__(self)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug(f'Thread {self.id} closed')
            return None
        except Exception:
            logger.error(f'Failed to join thread for Thrad {self.id}',
                         exc_info=True)
        return None

    def run(self):
        """List all available commands and their syntax."""
        logger.debug(f'Started new thread {self.id} for command {self.command}')
        if 'nblast-fafb' in self.command:
            response = '`nblast-fafb` blasts the provided neuron against the nightly dump of FAFB neurons. Use combinations of the following optional arguments to refine: \n'
            response += '1. Use `nblast-fafb <neuron> mirror` to mirror neuron before nblasting (if you are looking for the left version of your neuron). \n'
            response += '2. Use `nblast-fafb <neuron> hits=N` to return the top N hits in the 3D plot. Default is 3\n'
            response += '3. Use `nblast-fafb <neuron> cores=N` to set the number of CPU cores used to nblast. Default is 8\n'
            response += '4. Use `nblast-fafb <neuron> prefermu` to sort hits by mean of forward+reverse score rather than just forward score. Highly recommended!\n'
            response += '5. Use `nblast-fafb <neuron> usealpha` to make nblast emphasise straight backbones over smaller, wrigly neurites\n'
            response += '6. Use `nblast-fafb <neuron> autoseg` if your query neuron is in the FAFB autoseg instance\n'
        elif 'nblast' in self.command:
            response = '`nblast` blasts the provided neuron against the flycircuit (default) or Janelia GMR database. Use combinations of the following optional arguments to refine: \n'
            response += '1. Use `nblast <neuron> nomirror` to prevent mirroring of neurons before nblasting (i.e. if cellbody is already on the flys left). \n'
            response += '2. Use `nblast <neuron> hits=N` to return the top N hits in the 3D plot. Default is 3\n'
            response += '3. Use `nblast <neuron> gmrdb` to nblast against Janelia GMR lines instead of against flycircuit \n'
            response += '4. Use `nblast <neuron> cores=N` to set the number of CPU cores used to nblast. Default is 8\n'
            response += '5. Use `nblast <neuron> prefermu` to sort hits by mean of forward+reverse score rather than just forward score. Highly recommended!\n'
            response += '6. Use `nblast <neuron> usealpha` to make nblast emphasise straight backbones over smaller, wrigly neurites\n'
            response += '7. Use `nblast <neuron> autoseg` if your query neuron is in the FAFB autoseg instance\n'
        else:
            functions = [
                        '`url <neurons>` : give me a list of neurons and I will generate urls to their root nodes.',
                        '`nblast <neuron>` : give me a *single* neuron and let me run an nblast search. Use `@catbot help nblast` to learn more.',
                        '`nblast-fafb <neuron>` : `nblast` against a nightly dump of (simplified) CATMAID neurons. Use `@catbot help nblast-fafb` to learn more.',
                        '`help` : You have just used that, dummy...'
                        ]

            response = 'Currently I can help you with the following commands:'
            for f in functions:
                response += '\n' + f
            response += '\n You can pass me `<neurons>` either via their skids `#451234`, annotation `annotation="DA1"` or name `name="DA1 PN"`'

        if response:
            self.web_client.chat_postMessage(channel=self.channel,
                                             text=response,
                                             as_user=True)
        return


def time2hh():
    """Return witty response with time to HH."""
    # First get hours until next Friday
    friday = date.today()
    while friday.weekday() != 4:
        friday += timedelta(days=1)

    # Now get time until next Friday 5:30pm
    next_hh = datetime(friday.year, friday.month, friday.day, 17, 30)

    # If it is past 5:30 on a Friday, it's HH
    if next_hh <= datetime.now():
        return "It's Happy Hour time! Go have a drink :beer:"

    time2hh = next_hh - datetime.now()
    if time2hh.days > 0:
        return "It's {} days, {} hours and {} minutes " \
               "to Happy Hour :(".format(time2hh.days,
                                         time2hh.seconds // 3600,
                                         (time2hh.seconds // 60) % 60)
    elif time2hh.seconds // 3600 > 0:
        return "It's {} hours and {} minutes to " \
               "Happy Hour!".format(time2hh.seconds // 3600,
                                    (time2hh.seconds // 60) % 60)
    elif time2hh.seconds > 60:
        return "It's only another {} minutes to " \
               "Happy Hour :)".format((time2hh.seconds // 60) % 60)
    else:
        return "Oh boy, we're almost there! Give me a {} second " \
               "countdown!".format(time2hh.seconds)


def parse_command(msg):
    """Parse message to catbot."""
    command = msg.split(botconfig.AT_BOT)[1].strip()
    # Replace odd ” with "
    command = command.replace('”', '"')
    return command


def parse_neurons(command):
    """Parse the command in search of skeleton IDs, neuron names and annotations."""
    skids = []
    # First find skids:
    if re.findall('#(\d+)', command):
        skids += re.findall('#(\d+)', command)

    if 'name="' in command:
        skids += pymaid.get_skids_by_name(re.search('name="(.*?)"', command).group(1),
                                          allow_partial=True,
                                          remote_instance=remote_instance).skeleton_id.tolist()

    if 'annotation="' in command:
        skids += pymaid.get_skids_by_annotation(re.search('annotation="(.*?)"',
                                                          command).group(1),
                                                remote_instance=remote_instance)

    return list(set([int(n) for n in skids]))


class UserList:
    """Works like a dictionary mapping user ID to user name. The catch is it
    will update itself when ID for user is unknown (i.e. a new user was
    added on Slack).

    Will return 'unknown user' if no user for given ID is found.
    """

    def __init__(self, web_client):
        self.web_client = web_client
        self.update_users()

    def update_users(self):
        self.ul = self.web_client.users_list().data.get('members', {})
        self.dict = {e['id']: e['name'] for e in self.ul}

    def __getitem__(self, key):
        # Update user list if necessary
        if key not in self.dict:
            self.update_users()

        return self.dict.get(key, 'unknown user')

    def __getattr__(self, attr):
        return getattr(self.dict, attr)


@slack.RTMClient.run_on(event='message')
@respond_error
def parse_message(**payload):
    """Parse message from RTM client start thread for command if necessary."""
    # Now parse data
    data = payload['data']
    msg = data.get('text', '')

    # If this is not directed at me, ignore it
    if botconfig.AT_BOT not in msg:
        return

    # Parse remainder of message
    web_client = payload['web_client']
    channel = data['channel']
    user_id = data['user']
    user_name = user_list[user_id]

    logger.info(f'Message from {user_name} ({user_id}) in channel {channel}: {msg}')

    command = parse_command(msg)

    # First update how many open processes we have currently running
    # Try closing open threads
    if open_threads:
        for t in open_threads:
            if not t.is_alive():
                t.join()
                open_threads.remove(t)

    # Check if open processes have finished
    if open_processes:
        for p in open_processes:
            if p.poll() is not None:
                open_processes.remove(p)

    # Only process if not at max open threads
    if len(open_threads) + len(open_processes) > botconfig.MAX_PARALLEL_REQUESTS:
        logger.info('Too many open threads - ignoring command for now.')
        resp = 'I am currently really busy. Please give me a moment and try again. Cheers!'
        web_client.chat_postMessage(channel=channel,
                                    text=resp,
                                    as_user=True)
        return

    t = None
    if 'help' in command.lower():
        t = return_help(web_client, command, channel)
    elif 'url' in command.lower():
        t = return_url(web_client, command, channel)
    elif 'nblast' in command.lower():
        # For some odd reason, threading does not prevent
        # freezing while waiting R code to return nblast
        # results.
        # Therefore nblasting is used as a fire and forget
        # script by creating a new subprocess.

        # Parse skeleton IDs from command
        skids = parse_neurons(command)

        if len(skids) != 1:
            resp = f"I need a *single* neuron to nblast, got {len(skids)}."
            _ = web_client.chat_postMessage(text=resp,
                                            channel=channel,
                                            as_user=True)
            return

        skid = skids[0]

        autoseg = 'autoseg' in command.lower()
        if autoseg:
            rm = autoseg_instance
        else:
            rm = remote_instance

        if not pymaid.neuron_exists(skid, remote_instance=rm):
            resp = f"I'm sorry - the neuron {skid} does not " \
                    "seem to exists."
            _ = web_client.chat_postMessage(text=resp,
                                            channel=channel,
                                            as_user=True)
            return

        # Parse nblast parameters
        prefermu = 'prefermu' in command.lower()
        alpha = 'alpha' in command.lower()

        try:
            hits = int(re.search('hits=(\d+)',
                                 command.lower()).group(1))
        except BaseException:
            hits = 3

        try:
            cores = int(re.search('cores=(\d+)',
                                  command.lower()).group(1))
        except BaseException:
            cores = 8

        if 'gmrdb' in command.lower():
            db = 'gmr'
        else:
            db = 'fc'

        if 'fafb' in command.lower():
            mirror = 'mirror' in command.lower()
            cmd = f'python3 ffnblast_fafb.py {skid} {channel} {int(mirror)} ' \
                  f'{hits} {cores} {int(prefermu)} {int(alpha)} {int(autoseg)}'
        else:
            mirror = 'nomirror' not in command
            cmd = f'python3 ffnblast.py {skid} {channel} {int(mirror)} ' \
                  f'{hits} {db} {cores} {int(prefermu)} {int(alpha)} ' \
                  f'{int(autoseg)}'

        p = subprocess.Popen(cmd, shell=True)
        open_processes.append(p)
    elif 'happy' in command.lower() and 'hour' in command.lower():
        resp = time2hh()
        _ = web_client.chat_postMessage(text=resp,
                                        channel=channel,
                                        as_user=True)
    else:
        resp = "Not sure what you mean. Type " \
               "_@catbot help_ to get a list of " \
               "things I can do for you."
        _ = web_client.chat_postMessage(text=resp,
                                        channel=channel,
                                        as_user=True)

    if t:
        t.start()
        open_threads.append(t)

    # Update # of open processes if any changes
    global previous_open_threads
    n_open_threads = len(open_threads) + len(open_processes)
    if n_open_threads != previous_open_threads:
        logger.debug(f'Open threads/processes: {n_open_threads}')
        previous_open_threads = n_open_threads


if __name__ == '__main__':
    import sys

    # Create logger
    logger = logging.getLogger('pybotLog')
    # Create file handler which logs even debug messages
    fh = logging.FileHandler('pybot.log')
    fh.setLevel(logging.DEBUG)
    # Create console handler - define different log level is desired
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    # Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(name)s - '
                                  '%(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    # Add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)

    if 'debug' in sys.argv:
        logger.setLevel(logging.DEBUG)
        logger.info('Starting Pybot in Debug Mode...')
    else:
        logger.setLevel(logging.INFO)
        logger.info('Starting Pybot...')

    # botconfig.py holds credentials for CATMAID, Slack and Zotero
    try:
        import botconfig
    except BaseException:
        logger.error('Import of botconfig.py failed. Please make sure you'
                     ' have this configuration file correctly set up!')
        sys.exit()

    # Initialize CATMAID instance (without caching)
    remote_instance = pymaid.CatmaidInstance(botconfig.CATMAID_SERVER_URL,
                                             botconfig.CATMAID_HTTP_USER,
                                             botconfig.CATMAID_HTTP_PW,
                                             botconfig.CATMAID_AUTHTOKEN,
                                             project_id=botconfig.CATMAID_PROJECT_ID,
                                             caching=False)

    autoseg_instance = pymaid.CatmaidInstance(botconfig.AUTOSEG_SERVER_URL,
                                              botconfig.CATMAID_HTTP_USER,
                                              botconfig.CATMAID_HTTP_PW,
                                              botconfig.CATMAID_AUTHTOKEN,
                                              project_id=botconfig.CATMAID_PROJECT_ID,
                                              caching=False)

    # Set loggers and progress bars
    pymaid.set_pbars(hide=True)
    pymaid.set_loggers('ERROR')

    # Use these to keep track of how many threads and processes are open
    global open_threads
    global open_processes
    global previous_open_threads

    open_threads = []
    open_processes = []
    previous_open_threads = 0

    # Initialize slack client
    ssl_context = ssl_lib.create_default_context(cafile=certifi.where())
    web_client = slack.WebClient(token=botconfig.BOT_USER_OAUTH_ACCESS_TOKEN,
                                 ssl=ssl_context)
    rtm_client = slack.RTMClient(token=botconfig.BOT_USER_OAUTH_ACCESS_TOKEN,
                                 ssl=ssl_context,
                                 timeout=300)
    logger.info("Pybot connected and running!")

    # Initialize more stuff
    user_list = UserList(web_client)
    logger.debug('Users: ' + ', '.join(list(user_list.values())))

    # Extract ID of our bot user
    name2id = {e['name']: e['id'] for e in web_client.users_list().data['members']}

    if not name2id.get(botconfig.BOT_NAME):
        raise ValueError(f'ID for bot user "{botconfig.BOT_NAME}" not found.')

    botconfig.BOT_ID = name2id[botconfig.BOT_NAME]
    botconfig.AT_BOT = '<@' + botconfig.BOT_ID + '>'

    # Start the RTM client
    rtm_client.start()
